"""Replace only the engine wheel in this checkpoint's uninstalled candidate app."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / ".visionapp/compositional-authoring/VisionApp.app"


def main() -> None:
    support = BUNDLE / "Contents/Resources/engine"
    runtime = BUNDLE / "Contents/Resources/PythonRuntime"
    python = runtime / "bin/python3.12"
    manifest_path = support / "build.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["uv_lock_sha256"] == hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()
    native = BUNDLE / "Contents/MacOS/VisionApp"
    native_before = hashlib.sha256(native.read_bytes()).hexdigest()
    uv = REPO / ".venv/bin/uv"
    with tempfile.TemporaryDirectory(prefix="wheel-update-", dir=REPO / ".visionapp/compositional-authoring") as temporary:
        subprocess.run([str(uv), "build", "--offline", "--wheel", "--out-dir", temporary], cwd=REPO, check=True)
        wheel, = Path(temporary).glob("*.whl")
        subprocess.run([str(uv), "pip", "install", "--offline", "--python", str(python),
                        "--target", str(runtime / "lib/python3.12/site-packages"), "--link-mode", "copy",
                        "--reinstall-package", "visionapp-engine", "--no-deps", str(wheel)], cwd=REPO, check=True)
        manifest["engine_wheel_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    probe = ("from pathlib import Path; import engine; from engine.runtime_identity import source_identity; "
             "print(source_identity(Path(engine.__file__).resolve().parents[1]))")
    packaged = subprocess.check_output([str(python), "-I", "-B", "-c", probe], cwd=support, env=environment, text=True).strip()
    source = subprocess.check_output([str(REPO / ".venv/bin/python"), "-B", "-c", probe], cwd=REPO, env=environment, text=True).strip()
    assert source == packaged, (source, packaged)
    manifest["source_identity"] = packaged
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    assert hashlib.sha256(native.read_bytes()).hexdigest() == native_before
    subprocess.run(["codesign", "--force", "--sign", "-", "--options", "0", str(BUNDLE)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(BUNDLE)], check=True)
    subprocess.run([str(native), "--self-test"], cwd=support, env=environment, check=True)
    receipt = {"bundle": str(BUNDLE), "source_identity": packaged, "engine_wheel_sha256": manifest["engine_wheel_sha256"],
               "native_sha256": hashlib.sha256(native.read_bytes()).hexdigest(), "signature_verified": True,
               "scope": "Updated Python engine only in the uninstalled candidate; dependencies/native code unchanged; relocation and UI validation separate"}
    (REPO / "artifacts/compositional-authoring/candidate-wheel-update.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
