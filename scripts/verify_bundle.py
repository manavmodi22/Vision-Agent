"""Verify the packaged engine after relocation, without developer Python paths."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


def verify(bundle: Path, output: Path, image: Path | None, planner: str | None) -> None:
    bundle = bundle.resolve()
    result: dict[str, object] = {"bundle": str(bundle), "relocation_test": True}
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "VISION_REPO_ROOT"):
        environment.pop(key, None)
    environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    with tempfile.TemporaryDirectory(prefix="va-bundle-", dir="/tmp") as temporary:
        folder = Path(temporary)
        moved = folder / "Path with spaces" / "VisionApp.app"
        moved.parent.mkdir()
        shutil.move(str(bundle), moved)
        try:
            python = moved / "Contents/Resources/PythonRuntime/bin/python3.12"
            native = moved / "Contents/MacOS/VisionApp"
            environment["VISION_APP_BINARY"] = str(native)
            environment["VISION_DATA_DIR"] = str(folder / "data")
            paths_script = (
                "import sys,json,engine,torch,transformers,cv2; "
                "print(json.dumps({'python':sys.executable,'engine':engine.__file__,"
                "'paths':sys.path,'mps':torch.backends.mps.is_available()}))"
            )
            imports = json.loads(subprocess.check_output(
                [str(python), "-I", "-B", "-c", paths_script], cwd=folder, env=environment, text=True))
            assert Path(imports["engine"]).resolve().is_relative_to(moved.resolve()), imports
            assert all(Path(path).resolve().is_relative_to(moved.resolve()) for path in imports["paths"]), imports
            result["isolated_imports"] = imports
            packaged_skills = json.loads(subprocess.check_output(
                [str(python), "-I", "-B", "-c",
                 "import json; from agent.skills import select_skills; "
                 "print(json.dumps([s.reference.model_dump(mode='json') for s in "
                 "select_skills('Read printed labels and compare exact text')]))"],
                cwd=folder, env=environment, text=True))
            assert {skill["id"] for skill in packaged_skills} >= {"authoring", "reading"}, packaged_skills
            result["packaged_skill_references"] = packaged_skills
            result["native_checks"] = json.loads(subprocess.check_output(
                [str(native), "--self-test"], cwd=folder, env=environment, text=True))
            label = folder / "label.png"
            subprocess.run([str(python), "-I", "-B", "-c",
                "from PIL import Image,ImageDraw,ImageFont; import sys; "
                "im=Image.new('RGB',(1000,300),'white'); "
                "ImageDraw.Draw(im).text((40,60),'PALLET 12345\\nDOCK 4',fill='black',"
                "font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',64)); "
                "im.save(sys.argv[1])", str(label)], cwd=folder, env=environment, check=True)
            native_reading = subprocess.run([str(native), "--analyze-image", str(label)],
                                           cwd=folder, env=environment, text=True,
                                           capture_output=True, check=True)
            # Preserve the strict bridge response when a system diagnostic corrupts
            # stdout; silently extracting one JSON line would hide a runtime bug.
            result["apple_vision_process"] = {"stdout": native_reading.stdout,
                                               "stderr": native_reading.stderr}
            reading = json.loads(native_reading.stdout)
            assert "PALLET 12345" in reading["texts"] and "DOCK 4" in reading["texts"], reading
            result["apple_vision"] = reading
            socket_dir = folder / "socket"
            socket_dir.mkdir(mode=0o700)
            sock = socket_dir / "engine.sock"
            log = folder / "engine.log"
            with log.open("w") as stream:
                child = subprocess.Popen([str(python), "-B", "-m", "engine.api", "--socket", str(sock),
                                          "--data-dir", str(folder / "data")], cwd=folder,
                                         env=environment, stdout=stream, stderr=stream)
                try:
                    with httpx.Client(transport=httpx.HTTPTransport(uds=str(sock)),
                                      base_url="http://localhost", timeout=120) as client:
                        def call(method: str, path: str, body: object = None) -> object:
                            response = client.request(method, path, json=body)
                            response.raise_for_status()
                            return response.json()

                        deadline = time.monotonic() + 60
                        while True:
                            if child.poll() is not None:
                                raise RuntimeError(log.read_text())
                            try:
                                health = call("GET", "/health")
                                break
                            except httpx.TransportError:
                                if time.monotonic() > deadline:
                                    raise RuntimeError(log.read_text()) from None
                                time.sleep(0.2)
                        result["health"] = health
                        catalog = call("GET", "/capabilities")
                        assert isinstance(catalog, dict) and catalog.get("capabilities"), catalog
                        result["capability_catalog"] = catalog
                        project = call("POST", "/projects", {"name": "Isolated bundle verification", "use_case": "pallets"})
                        assert isinstance(project, dict)
                        project_id = str(project["id"])
                        call("POST", f"/projects/{project_id}/demo")
                        call("POST", f"/projects/{project_id}/plan", {"mode": "template", "model": "fixture-color-v1"})
                        result["fixture_preview"] = call("POST", f"/projects/{project_id}/preview", {})
                        result["fixture_evaluation"] = call("POST", f"/projects/{project_id}/evaluate", {})
                        if planner:
                            settings = call("GET", "/settings")
                            assert isinstance(settings, dict)
                            settings.update(planner_model=planner, model_url="http://127.0.0.1:1234/v1")
                            call("PUT", "/settings", settings)
                            call("POST", f"/projects/{project_id}/deploy", {"approved": True})
                            call("POST", f"/projects/{project_id}/run", {"max_frames": 10})
                            stored = call("GET", f"/projects/{project_id}/events")
                            assert isinstance(stored, list)
                            expected = sum(row["label"] == "pallet" and row["payload"].get("zone") == "A" for row in stored)
                            answer = call("POST", f"/projects/{project_id}/ask", {
                                "question": "How many pallet observations were recorded in lane A today?",
                                "timezone": "America/Los_Angeles",
                            })
                            assert isinstance(answer, dict) and answer.get("interpretation"), answer
                            assert answer["interpretation"]["matched_observations"] == expected, answer
                            result["actual_semantic_question"] = answer
                        if image is not None:
                            custom = call("POST", "/projects", {"name": "Real inference bundle probe", "use_case": "custom"})
                            assert isinstance(custom, dict)
                            custom_id = str(custom["id"])
                            call("POST", f"/projects/{custom_id}/media", {"paths": [str(image.resolve())]})
                            manifest = call("GET", f"/projects/{custom_id}/dataset")
                            assert isinstance(manifest, dict)
                            call("PUT", f"/projects/{custom_id}/dataset/classes", {
                                "base_revision": manifest["revision"],
                                "classes": [{"id": "person", "name": "person", "color": "#43C6AC"}],
                            })
                            call("POST", f"/projects/{custom_id}/plan", {"mode": "template", "model": "owlv2-base-patch16"})
                            result["actual_detector_preview"] = call("POST", f"/projects/{custom_id}/preview", {})
                        result["models"] = call("GET", "/models")
                finally:
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(moved)], check=True)
            result["signature_after_execution"] = "passed"
            result["status"] = "passed"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n")
        except Exception as error:
            result["status"] = "failed"
            result["error"] = f"{type(error).__name__}: {error}"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n")
            raise
        finally:
            shutil.move(str(moved), bundle)
    print(f"Relocation, packaged inference and signature checks passed: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/bundle-verification.json"))
    parser.add_argument("--image", type=Path)
    parser.add_argument("--planner", help="Optional actual local planner id at port 1234")
    arguments = parser.parse_args()
    verify(arguments.bundle, arguments.output, arguments.image, arguments.planner)
