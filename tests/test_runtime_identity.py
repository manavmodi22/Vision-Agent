import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from engine.runtime_identity import runtime_identity, source_identity


def test_source_identity_changes_only_for_source(tmp_path: Path) -> None:
    for name in ("agent", "engine", "mcp_server", "spec"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "__init__.py").write_text(f"# {name}\n")
    value = source_identity(tmp_path)
    assert value == "c9f5e4d0f8e04aeb91b4715b27e112e1c5248826182a4582a87dc253aecbd8a4"
    (tmp_path / "engine/cache.pyc").write_bytes(b"cache")
    assert source_identity(tmp_path) == value
    (tmp_path / "engine/__init__.py").write_text("# edited\n")
    assert source_identity(tmp_path) != value
    identity = runtime_identity(tmp_path)
    assert identity["data_dir"] == str(tmp_path.resolve())
    assert identity["python"] == str(Path(sys.executable).resolve())


def test_packaged_skill_guidance_is_part_of_runtime_identity(tmp_path: Path) -> None:
    package = tmp_path / "agent/skills/packages/reading"
    package.mkdir(parents=True)
    (tmp_path / "agent/__init__.py").write_text("# package\n")
    initial = source_identity(tmp_path)
    skill = package / "SKILL.md"
    skill.write_text("# Reading v1\n")
    first = source_identity(tmp_path)
    assert first != initial
    skill.write_text("# Reading v2\n")
    assert source_identity(tmp_path) != first
    (tmp_path / "agent/notes.md").write_text("Unpackaged engineering notes\n")
    final = source_identity(tmp_path)
    (tmp_path / "agent/notes.md").write_text("Different engineering notes\n")
    assert source_identity(tmp_path) == final


def test_supervised_engine_exits_after_parent_dies() -> None:
    with tempfile.TemporaryDirectory(prefix="va-parent-", dir="/tmp") as temp:
        root = Path(temp)
        sock = root / "engine.sock"
        script = (
            "import os,subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-m','engine.api','--socket',sys.argv[1],"
            "'--data-dir',sys.argv[2],'--parent-pid',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "print(child.pid,flush=True); time.sleep(60)"
        )
        owner = subprocess.Popen([sys.executable, "-c", script, str(sock), str(root / "data")],
                                 stdout=subprocess.PIPE, text=True)
        assert owner.stdout is not None
        pid = int(owner.stdout.readline())
        try:
            with httpx.Client(transport=httpx.HTTPTransport(uds=str(sock)), base_url="http://localhost", timeout=3) as client:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        response = client.get("/health")
                        response.raise_for_status()
                        assert response.json()["runtime"]["pid"] == pid
                        break
                    except httpx.TransportError:
                        assert time.monotonic() < deadline
                        time.sleep(0.1)
            owner.terminate()
            owner.wait(timeout=3)
            deadline = time.monotonic() + 3
            while True:
                state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
                if not state or state.startswith("Z"):
                    break
                assert time.monotonic() < deadline, f"Supervised engine {pid} survived its parent"
                time.sleep(0.1)
        finally:
            if owner.poll() is None:
                owner.terminate()
                owner.wait(timeout=3)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
