"""Assemble a relocatable runtime from uv-managed Python and locked wheels."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

PYTHON_VERSION = "3.12.14"
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def command(*args: str, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def is_macho(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as stream:
        return stream.read(4) in MACHO_MAGICS


def clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        environment.pop(key, None)
    environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    return environment


def assemble(root: Path, destination: Path, identity: str) -> None:
    uv = shutil.which("uv") or str(root / ".venv/bin/uv")
    if not Path(uv).is_file():
        raise ValueError("Install uv or run the project bootstrap before packaging")
    cache = root / ".visionapp/python"
    command(uv, "python", "install", "--install-dir", str(cache), PYTHON_VERSION, cwd=root)
    runtimes = list(cache.glob(f"cpython-{PYTHON_VERSION}-macos-aarch64-none"))
    if len(runtimes) != 1:
        raise ValueError("Expected one pinned Apple silicon standalone Python runtime")
    source_runtime = runtimes[0].resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visionapp-build-", dir=root / ".visionapp") as temp:
        staging = Path(temp) / "VisionApp.app"
        contents = staging / "Contents"
        binary_dir = contents / "MacOS"
        support = contents / "Resources/engine"
        runtime = contents / "Resources/PythonRuntime"
        binary_dir.mkdir(parents=True)
        support.mkdir(parents=True)
        shutil.copy2(root / "app/.build/release/VisionApp", binary_dir / "VisionApp")
        shutil.copy2(root / "app/Info.plist", contents / "Info.plist")
        shutil.copytree(source_runtime, runtime, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        python = runtime / "bin/python3.12"
        site = runtime / "lib/python3.12/site-packages"
        requirements = Path(temp) / "requirements.txt"
        command(uv, "export", "--frozen", "--extra", "vision", "--no-dev", "--no-emit-project",
                "--format", "requirements-txt", "--output-file", str(requirements), cwd=root)
        command(uv, "pip", "install", "--python", str(python), "--target", str(site),
                "--link-mode", "copy", "--require-hashes", "--requirements", str(requirements), cwd=root)
        wheel_dir = Path(temp) / "wheels"
        command(uv, "build", "--wheel", "--out-dir", str(wheel_dir), cwd=root)
        wheels = list(wheel_dir.glob("visionapp_engine-*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected one engine wheel")
        command(uv, "pip", "install", "--python", str(python), "--target", str(site),
                "--link-mode", "copy", "--no-deps", str(wheels[0]), cwd=root)
        # No entrypoint scripts are required; all children use the bundled python -m.
        shutil.copy2(requirements, support / "locked-requirements.txt")
        environment = clean_environment()
        inventory_script = (
            "import importlib.metadata as m,json,sys; "
            "print(json.dumps({'python':sys.version,'packages':sorted("
            "[{'name':d.metadata['Name'],'version':d.version,"
            "'license':d.metadata.get('License-Expression') or d.metadata.get('License',''),"
            "'license_files':list(d.metadata.get_all('License-File') or [])} "
            "for d in m.distributions()],key=lambda p:p['name'].lower())},indent=2))"
        )
        inventory = subprocess.check_output([str(python), "-I", "-B", "-c", inventory_script],
                                            cwd=support, env=environment, text=True)
        (support / "dependencies.json").write_text(inventory)
        (support / "build.json").write_text(json.dumps({
            "format": 1, "python": PYTHON_VERSION, "architecture": "arm64", "relocatable": True,
            "python_provider": "astral-sh/python-build-standalone via uv", "notarized": False,
            "signing": "ad-hoc" if identity == "-" else "Developer ID requested",
            "hardened_runtime": identity != "-",
            "engine_wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
            "uv_lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        }, indent=2) + "\n")
        command(str(python), "-I", "-B", "-c",
                "import engine.api.application, agent.planner, mcp_server.server; "
                "import torch, transformers, cv2, onnxruntime; print('Bundled imports passed')", cwd=support, env=environment)
        for notice in ("engine/models/licenses/YOLOX-Apache-2.0.txt",
                       "engine/models/licenses/YOLOX-NOTICE.md",
                       "onnxruntime/LICENSE", "onnxruntime/ThirdPartyNotices.txt"):
            path = site / notice
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"Bundled adapter/runtime attribution is missing: {notice}")
        for path in staging.rglob("*"):
            if path.is_symlink() and not path.resolve().is_relative_to(staging.resolve()):
                raise ValueError(f"Bundle contains an external symlink: {path.relative_to(staging)}")
        executables = [path for path in staging.rglob("*")
                       if path != binary_dir / "VisionApp" and is_macho(path)]
        for path in sorted(executables, key=lambda p: len(p.parts), reverse=True):
            args = ["codesign", "--force", "--sign", identity]
            if identity != "-":
                args.extend(["--options", "runtime", "--timestamp"])
            else:
                args.extend(["--options", "0"])
            command(*args, str(path), cwd=root)
        bundle_sign = ["codesign", "--force", "--sign", identity]
        if identity != "-":
            bundle_sign.extend(["--options", "runtime", "--timestamp"])
        else:
            bundle_sign.extend(["--options", "0"])
        command(*bundle_sign, str(staging), cwd=root)
        command("codesign", "--verify", "--deep", "--strict", str(staging), cwd=root)
        command(str(binary_dir / "VisionApp"), "--self-test", cwd=support, env=environment)
        backup = destination.with_name(destination.name + ".previous")
        if backup.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
            backup = destination.with_name(destination.name + f".previous-{stamp}")
        if destination.exists():
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
        print(f"Built relocatable {'locally signed' if identity == '-' else 'signed'} app: {destination}")
        if backup.exists():
            print(f"Prior build retained at {backup}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    assemble(repo, options.output or repo / "dist/VisionApp.app",
             os.environ.get("VISION_SIGN_IDENTITY", "-"))
