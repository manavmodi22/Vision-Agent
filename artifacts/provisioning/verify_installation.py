"""Actual public download, API approval, installed inference and replay verification.

All model files and state stay in a newly created isolated workspace. No existing
models, projects, annotations, approvals, or external deliveries are modified.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from engine.api.application import create_app
from engine.runtime_identity import source_identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    args = parser.parse_args()
    if args.workspace.exists() or args.output.exists() or args.fixtures.exists():
        raise ValueError("Use fresh paths; earlier evidence must be retained")
    repo = Path(__file__).resolve().parents[2]
    expected = source_identity(repo)
    models = args.workspace.resolve() / "models"
    os.environ["VISION_MODELS_DIR"] = str(models)
    report: dict[str, object] = {"runtime_source_identity": expected, "workspace": str(args.workspace.resolve()),
        "models_directory": str(models), "passed": False,
        "scope": "Actual API installation from public pinned official artifacts into isolated storage, with one generated-black-image inference. No model quality, user project, annotation, or deployment claim."}
    fixtures: dict[str, object] = {}
    started = time.monotonic()
    try:
        with TestClient(create_app(args.workspace.resolve() / "data")) as client:
            def request(method: str, path: str, body: object = None) -> object:
                response = client.request(method, path, json=body)
                response.raise_for_status()
                return response.json()

            options = request("GET", "/provisioning/options")
            assert isinstance(options, dict)
            option = next(row for row in options["options"] if row["model_id"] == "yolox-s-onnx-coco")
            assert option["action"] == "install" and not option["blockers"]
            plan = request("POST", "/provisioning/plans", {"model_id": option["model_id"]})
            assert isinstance(plan, dict) and not plan["blockers"] and plan["action"] == "install"
            assert not models.exists(), "Reviewing a plan must not start model installation"
            approval = {"plan_id": plan["id"], "plan_hash": plan["plan_hash"], "approved": True}
            rejected = client.post("/provisioning/jobs", json={**approval, "approved": False})
            assert rejected.status_code == 400
            stale = client.post("/provisioning/jobs", json={**approval, "plan_hash": "0" * 64})
            assert stale.status_code == 409
            assert not models.exists(), "Rejected approval must not start model installation"
            job = request("POST", "/provisioning/jobs", approval)
            assert isinstance(job, dict)
            repeated = request("POST", "/provisioning/jobs", approval)
            assert isinstance(repeated, dict) and repeated["id"] == job["id"]
            deadline = time.monotonic() + plan["max_duration_s"] + 35
            last_phase = None
            while job["status"] in {"queued", "running"}:
                if job["phase"] != last_phase:
                    print(json.dumps({"phase": job["phase"], "message": job["message"]}), flush=True)
                    last_phase = job["phase"]
                if time.monotonic() > deadline:
                    raise TimeoutError("Actual provisioning job exceeded the observed time budget")
                time.sleep(.5)
                job = request("GET", "/provisioning/jobs/" + job["id"])
                assert isinstance(job, dict)
            report["job"] = job
            assert job["status"] == "completed", job.get("error")
            assert job["result"]["installed"] and job["result"]["smoke_status"] == "passed"
            health = request("GET", "/provisioning/health/" + job["result"]["health_receipt_id"])
            assert isinstance(health, dict) and health["quality_claim"] == "none"
            replay = request("POST", "/provisioning/jobs", approval)
            assert isinstance(replay, dict) and replay["id"] == job["id"]
            catalog = request("GET", "/capabilities")
            assert isinstance(catalog, dict)
            capability = next(row for row in catalog["capabilities"] if row["id"] == plan["capability_id"])
            assert capability["callable"] and capability["readiness"]["evidence_scope"] == "inference_smoke"
            after = request("GET", "/provisioning/options")
            assert isinstance(after, dict)
            current = next(row for row in after["options"] if row["model_id"] == plan["model_id"])
            assert current["action"] == "validate" and current["download_bytes"] == 0
            fixtures = {"options": options, "plan": plan, "job": job, "health": health}
            report.update(passed=True, plan=plan, health=health, installed_capability=capability,
                          approval_required=True, mismatched_hash_rejected=True,
                          start_replay_same_job=True, completed_replay_same_job=True)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    report.update(elapsed_s=time.monotonic() - started, source_unchanged=source_identity(repo) == expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if fixtures:
        args.fixtures.mkdir(parents=True)
        for name, value in fixtures.items():
            (args.fixtures / (name + ".json")).write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_s", "source_unchanged")}), flush=True)
    if not report["passed"] or not report["source_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
