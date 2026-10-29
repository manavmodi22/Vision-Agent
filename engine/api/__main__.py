"""Launch the engine with a private Unix socket; never bind a TCP port."""
from __future__ import annotations

import argparse
import os
import socket
import stat
import threading
from pathlib import Path

import uvicorn

from engine.api.application import create_app


def default_data_dir() -> Path:
    return Path(os.environ.get("VISION_DATA_DIR", str(Path.home() / "Library/Application Support/VisionApp")))


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionApp local engine")
    parser.add_argument("--socket", default=os.environ.get("VISION_SOCKET", f"/tmp/visionapp-{os.getuid()}/engine.sock"))
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--parent-pid", type=int, help="Exit when the supervising native app exits")
    args = parser.parse_args()
    if args.parent_pid is not None:
        if args.parent_pid <= 1 or os.getppid() != args.parent_pid:
            parser.error("The supervising parent process is no longer present")
        parent_pid = args.parent_pid

        def watch_parent() -> None:
            while True:
                threading.Event().wait(0.5)
                if os.getppid() != parent_pid:
                    # Forced app exits cannot run shutdown; next startup reconciles jobs.
                    os._exit(1)

        threading.Thread(target=watch_parent, daemon=True, name="native-parent-watch").start()
    target = Path(args.socket).expanduser().absolute()
    if len(os.fsencode(target)) >= 104:
        parser.error("Socket path must be shorter than 104 bytes on macOS")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_stat = target.parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
        parser.error("Socket parent must be owned by this user with permissions 0700")
    if target.exists():
        if not stat.S_ISSOCK(target.lstat().st_mode):
            parser.error("Refusing to replace a non-socket file")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(str(target)) == 0:
                parser.error("An engine is already listening on this socket")
        target.unlink()
    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(target))
    target.chmod(0o600)
    listener.listen(128)
    listener.setblocking(False)
    config = uvicorn.Config(create_app(args.data_dir), log_level="info", access_log=False,
                            timeout_graceful_shutdown=1)
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()
        target.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
