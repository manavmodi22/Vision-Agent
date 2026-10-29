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


def verify(bundle: Path, output: Path, image: Path | None, planner: str | None,
           yolox_model_directory: Path | None = None) -> None:
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
            if yolox_model_directory is not None:
                isolated_models = folder / "models"
                shutil.copytree(yolox_model_directory.resolve(), isolated_models / "yolox-s-onnx-coco")
                environment["VISION_MODELS_DIR"] = str(isolated_models)
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
            rich_reading = json.loads(subprocess.check_output(
                [str(python), "-I", "-B", "-c",
                 "from PIL import Image; import sys; "
                 "from engine.adapters.contracts import OcrRequest; "
                 "from engine.adapters.registry import run_inference; "
                 "print(run_inference(Image.open(sys.argv[1]),OcrRequest()).model_dump_json())",
                 str(label)], cwd=folder, env=environment, text=True, timeout=40))
            assert {row["text"] for row in rich_reading["readings"]} == {"PALLET 12345", "DOCK 4"}, rich_reading
            assert all(row["polygon"] and row["box"] and row["confidence"] is not None
                       for row in rich_reading["readings"]), rich_reading
            assert rich_reading["identity"]["system_identity"]["output_protocol"] == "2", rich_reading
            result["apple_vision_common_adapter"] = rich_reading
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
                        evaluation = call("POST", f"/projects/{project_id}/evaluate", {})
                        assert isinstance(evaluation, dict)
                        assert evaluation.get("protocol_id") and evaluation.get("protocol_hash"), evaluation
                        assert evaluation.get("promotion_eligible") is False, evaluation
                        result["fixture_evaluation"] = evaluation
                        rejection = client.post(f"/projects/{project_id}/deploy", json={"approved": True})
                        assert rejection.status_code == 400 and "acceptance" in rejection.text.lower(), rejection.text
                        result["fixture_promotion_rejected"] = rejection.json()
                        rejection = client.post(f"/projects/{project_id}/deploy", json={
                            "approved": True, "approval_scope": "local_trial"})
                        assert rejection.status_code == 400 and "reason" in rejection.text.lower(), rejection.text
                        result["trial_without_reason_rejected"] = rejection.json()
                        trial = call("POST", f"/projects/{project_id}/deploy", {
                            "approved": True, "approval_scope": "local_trial",
                            "override_reason": "Verify the isolated packaged software fixture workflow locally.",
                        })
                        assert isinstance(trial, dict) and trial.get("approval_scope") == "local_trial", trial
                        assert trial.get("external_delivery_enabled_by_approval") is False, trial
                        result["explicit_local_trial"] = trial
                        if yolox_model_directory is not None:
                            install_plan = call("POST", "/provisioning/plans", {"model_id": "yolox-s-onnx-coco"})
                            assert isinstance(install_plan, dict) and install_plan["action"] == "validate", install_plan
                            assert not install_plan["blockers"] and install_plan["total_download_bytes"] == 0, install_plan
                            install_job = call("POST", "/provisioning/jobs", {
                                "plan_id": install_plan["id"], "plan_hash": install_plan["plan_hash"], "approved": True})
                            assert isinstance(install_job, dict)
                            deadline = time.monotonic() + 120
                            while install_job["status"] in {"queued", "running"}:
                                if time.monotonic() > deadline:
                                    raise TimeoutError("Packaged ONNX validation exceeded 120 seconds")
                                time.sleep(.2)
                                install_job = call("GET", "/provisioning/jobs/" + str(install_job["id"]))
                                assert isinstance(install_job, dict)
                            assert install_job["status"] == "completed", install_job
                            install_result = install_job["result"]
                            assert isinstance(install_result, dict) and install_result["smoke_status"] == "passed"
                            receipt = call("GET", "/provisioning/health/" + str(install_result["health_receipt_id"]))
                            result["packaged_yolox_validation"] = {"plan": install_plan, "job": install_job,
                                "health": receipt, "scope": "Relocated packaged CPU inference on generated black pixels using an isolated copy of pinned weights; no network download or accuracy claim."}
                        if planner:
                            settings = call("GET", "/settings")
                            assert isinstance(settings, dict)
                            settings.update(planner_model=planner, model_url="http://127.0.0.1:1234/v1")
                            call("PUT", "/settings", settings)
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
                            detector_model = "yolox-s-onnx-coco" if yolox_model_directory is not None else "owlv2-base-patch16"
                            call("POST", f"/projects/{custom_id}/plan", {"mode": "template", "model": detector_model})
                            result["actual_detector_model"] = detector_model
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
    parser.add_argument("--image", type=Path, help="Preview one actual image with YOLOX when --yolox-model-directory is supplied, otherwise OWLv2")
    parser.add_argument("--planner", help="Optional actual local planner id at port 1234")
    parser.add_argument("--yolox-model-directory", type=Path,
                        help="Copy this existing pinned YOLOX directory into temporary storage and validate packaged ONNX inference")
    arguments = parser.parse_args()
    verify(arguments.bundle, arguments.output, arguments.image, arguments.planner, arguments.yolox_model_directory)
