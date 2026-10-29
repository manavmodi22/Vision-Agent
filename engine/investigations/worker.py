"""One owned probe process with deadline and process-group cleanup."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
import threading
from pathlib import Path

from pydantic import TypeAdapter

from spec.investigation import BuilderAction


async def run_owned_probe(data_dir: Path, project_id: str, task_id: str,
                          action_id: str, action: BuilderAction, timeout_s: float) -> dict[str, object]:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "engine.investigations.worker",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    request = {"data_dir": str(data_dir), "project_id": project_id, "task_id": task_id,
               "action_id": action_id, "action": action.model_dump(mode="json"), "parent_pid": os.getpid()}
    try:
        async with asyncio.timeout(timeout_s):
            output, error = await process.communicate(json.dumps(request).encode())
        if process.returncode:
            raise ValueError(f"Probe worker exited {process.returncode}: {error.decode(errors='replace')[-1000:]}")
        if len(output) > 4 * 1024 * 1024:
            raise ValueError("Probe output exceeded its bounded transport size")
        payload = json.loads(output)
        if not isinstance(payload, dict):
            raise ValueError("Probe worker returned an invalid result")
        return payload
    finally:
        # The worker may have exited before one of its native children. Its
        # dedicated process group is ours even after the leader exits.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                pass
        # A completed leader does not imply that its children exited. Native
        # children that ignore TERM must not survive a completed/cancelled probe.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if process.returncode is None:
            await process.wait()


def main() -> None:
    request = json.loads(sys.stdin.buffer.read(65537))
    parent = request["parent_pid"]
    done = threading.Event()

    def watch_parent() -> None:
        while not done.wait(.25):
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=watch_parent, daemon=True).start()
    try:
        from engine.investigations.store import InvestigationStore
        from engine.investigations.tools import InvestigationTools
        from engine.service import WorkspaceService

        service = WorkspaceService(Path(request["data_dir"]))
        action = TypeAdapter(BuilderAction).validate_python(request["action"])
        # Library diagnostics must not corrupt the typed result channel.
        with contextlib.redirect_stdout(sys.stderr):
            if action.type == "construct_workflow":
                from engine.investigations.workflows import construct_workflow
                outcome = construct_workflow(service, InvestigationStore(service), request["project_id"],
                                             request["task_id"], request["action_id"], action)
            else:
                outcome = InvestigationTools(service, InvestigationStore(service)).execute(
                    request["project_id"], request["task_id"], request["action_id"], action)
        sys.stdout.write(outcome.model_dump_json())
        sys.stdout.flush()
    finally:
        # Completion can race the watcher's next tick. A lost coordinator cannot
        # collect this result or clean up children, so close our entire group.
        if os.getppid() != parent:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        done.set()


if __name__ == "__main__":
    main()
