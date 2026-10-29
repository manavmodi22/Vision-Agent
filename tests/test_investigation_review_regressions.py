"""Focused review regressions; process tests execute production lifecycle code."""
import asyncio
import contextlib
import json
import os
import signal
import sys
from pathlib import Path

import pytest


async def process_running(pid: int) -> bool:
    process = await asyncio.create_subprocess_exec("ps", "-o", "stat=", "-p", str(pid), stdout=asyncio.subprocess.PIPE)
    output, _ = await process.communicate()
    return bool(output.strip() and not output.strip().startswith(b"Z"))


@pytest.mark.skipif(os.name != "posix", reason="Worker parent monitoring requires POSIX process groups")
@pytest.mark.parametrize("finish_after_parent_exit", [False, True])
async def test_abrupt_parent_exit_does_not_leave_term_ignoring_native_child(
    tmp_path: Path, finish_after_parent_exit: bool,
) -> None:
    """The real worker parent watcher must clean up even if its coordinator crashes."""
    child_marker = tmp_path / "child.pid"
    worker_marker = tmp_path / "worker.pid"
    child_code = ("import os,signal,time;from pathlib import Path;"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                  f"Path({str(child_marker)!r}).write_text(str(os.getpid()));time.sleep(30)")
    worker_code = (
        "import os,subprocess,sys,time\n"
        "from engine.investigations import tools,worker\n"
        "def native_work(*args):\n"
        " parent=os.getppid()\n"
        f" subprocess.Popen([sys.executable,'-c',{child_code!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        + (" while os.getppid()==parent: time.sleep(.001)\n"
           " return tools.ToolOutcome(payload={'execution_finished':True})\n" if finish_after_parent_exit else " time.sleep(30)\n") +
        "tools.InvestigationTools.execute=native_work\n"
        "worker.main()\n"
    )
    request = {"data_dir": str(tmp_path / "workspace"), "project_id": "project", "task_id": "task",
               "action_id": "action", "action": {"type": "inspect_media"}}
    parent_code = (
        "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
        f"p=subprocess.Popen([sys.executable,'-c',{worker_code!r}],stdin=subprocess.PIPE,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)\n"
        f"Path({str(worker_marker)!r}).write_text(str(p.pid))\n"
        f"request=json.loads({json.dumps(request)!r});request['parent_pid']=os.getpid()\n"
        "p.stdin.write(json.dumps(request).encode());p.stdin.close();time.sleep(30)\n"
    )
    parent = await asyncio.create_subprocess_exec(sys.executable, "-c", parent_code)
    child_pid = worker_pid = None
    try:
        for _ in range(200):
            if child_marker.exists():
                break
            await asyncio.sleep(.1)
        assert child_marker.exists(), "Native child did not start"
        child_pid = int(child_marker.read_text())
        worker_pid = int(worker_marker.read_text())
        parent.kill()
        await parent.wait()
        for _ in range(50):
            if not await process_running(child_pid):
                break
            await asyncio.sleep(.05)
        assert not await process_running(worker_pid), "Parent watcher did not stop the worker"
        assert not await process_running(child_pid), "Worker parent watcher left a TERM-ignoring native child running"
    finally:
        if parent.returncode is None:
            parent.kill()
            await parent.wait()
        if worker_pid is None and worker_marker.exists():
            worker_pid = int(worker_marker.read_text())
        if worker_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(worker_pid, signal.SIGKILL)
        if child_pid is None and child_marker.exists():
            child_pid = int(child_marker.read_text())
        if child_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
