"""Actual owned-process cleanup, including a stubborn child after leader exit."""
import asyncio
import contextlib
import os
import signal
import sys
from pathlib import Path

import pytest

from engine.investigations.worker import run_owned_probe
from spec.investigation import InspectMedia


@pytest.mark.skipif(os.name != "posix", reason="Owned process groups require POSIX")
async def test_completed_worker_does_not_leave_term_ignoring_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_marker = tmp_path / "child.pid"
    child_code = ("import os,signal,time;from pathlib import Path;"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                  f"Path({str(child_marker)!r}).write_text(str(os.getpid()));time.sleep(30)")
    leader_code = ("import subprocess,sys,time,json;from pathlib import Path\n"
                   f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                   "for _ in range(100):\n"
                   f" if Path({str(child_marker)!r}).exists(): break\n"
                   " time.sleep(.01)\n"
                   "print(json.dumps({'child':p.pid}),flush=True)\n")
    original = asyncio.create_subprocess_exec

    async def launch(*_args: object, **kwargs: object) -> asyncio.subprocess.Process:
        return await original(sys.executable, "-c", leader_code, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    pid = None
    try:
        outcome = await run_owned_probe(tmp_path, "project", "task", "action", InspectMedia(type="inspect_media"), 5)
        pid = int(str(outcome["child"]))
        assert child_marker.read_text() == str(pid)
        for _ in range(40):
            probe = await original("ps", "-o", "stat=", "-p", str(pid), stdout=asyncio.subprocess.PIPE)
            stdout, _ = await probe.communicate()
            # A zombie has exited and cannot execute; the OS may reap it later.
            if not stdout.strip() or stdout.strip().startswith(b"Z"):
                break
            await asyncio.sleep(.05)
        else:
            pytest.fail(f"Worker left child {pid} running after leader exit")
    finally:
        if pid is None and child_marker.exists():
            pid = int(child_marker.read_text())
        if pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
