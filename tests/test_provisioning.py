"""Reviewed install boundaries. Network and smoke are mocked; no model quality claim."""
from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from engine.api import create_app
from engine.provisioning import ProvisioningConflict, ProvisioningManager
from engine.provisioning.download import download_artifact
from engine.provisioning.registry import RECIPES, YOLOX
from engine.provisioning.state import current_health
from spec.provisioning import ProvisioningArtifact, ProvisioningJobRequest

BLACK = hashlib.sha256(b"RGB\0" + struct.pack(">II", 640, 640) + bytes(640 * 640 * 3)).hexdigest()


@pytest.fixture()
def mocked_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "models"))
    contents = {"model.onnx": b"Explicit software fixture; not ONNX weights", "LICENSE.txt": b"Test license fixture"}
    artifacts = tuple(ProvisioningArtifact(filename=name, source_url="https://github.com/test/" + name,
        expected_sha256=hashlib.sha256(value).hexdigest(), expected_bytes=len(value)) for name, value in contents.items())
    monkeypatch.setitem(RECIPES, YOLOX.model_id, replace(YOLOX, name="Software contract fixture; inference mocked",
        artifacts=artifacts, packages=()))
    requests: list[str] = []
    original_client = httpx.Client
    def response(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, stream=ByteStream(contents[request.url.path.rsplit("/", 1)[1]]))
    monkeypatch.setattr("engine.provisioning.manager.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(response), **kwargs))
    monkeypatch.setattr(ProvisioningManager, "_smoke", lambda *args: {
        "input_sha256": BLACK, "elapsed_s": .001, "observation_count": 0, "execution_identity_hash": "b" * 64})
    monkeypatch.setattr("engine.adapters.identity.resolve_execution_identity",
        lambda _: SimpleNamespace(identity_hash="b" * 64, unavailable_artifacts=[]))
    app = create_app(tmp_path / "workspace")
    return TestClient(app), app.state.provisioning, contents, requests


class ByteStream(httpx.SyncByteStream):
    def __init__(self, value: bytes) -> None:
        self.value = value

    def __iter__(self):  # type: ignore[no-untyped-def]
        for offset in range(0, len(self.value), 7):
            yield self.value[offset:offset + 7]


def wait_job(manager: ProvisioningManager, identifier: str):  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.get(identifier)
        if job.status not in {"queued", "running"}:
            return job
        time.sleep(.01)
    pytest.fail("Bounded mocked worker did not finish")


def test_options_review_and_exact_approval_have_no_implicit_effects(mocked_install, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    client, manager, _, requests = mocked_install
    options = client.get("/provisioning/options")
    assert options.status_code == 200 and options.json()["options"][0]["action"] == "install"
    plan = client.post("/provisioning/plans", json={"model_id": YOLOX.model_id}).json()
    assert client.get("/provisioning/plans/" + plan["id"]).json() == plan
    assert plan["license"]["status"] == "declared" and plan["artifacts"][0]["expected_sha256"]
    assert requests == [] and not (tmp_path / "models").exists()
    assert client.post("/provisioning/plans", json={"model_id": "https://evil.invalid/weights"}).status_code == 400
    assert client.post("/provisioning/plans", json={"model_id": YOLOX.model_id, "url": "https://evil.invalid"}).status_code == 422
    assert client.post("/provisioning/jobs", json={"plan_id": plan["id"], "plan_hash": plan["plan_hash"], "approved": False}).status_code == 400
    assert client.post("/provisioning/jobs", json={"plan_id": plan["id"], "plan_hash": "a" * 64, "approved": True}).status_code == 409
    assert not requests and manager.jobs() == []


def test_missing_recipe_dependency_still_blocks_approval(mocked_install, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _, manager, _, requests = mocked_install
    missing = "visionapp-explicitly-absent-test-runtime"
    monkeypatch.setitem(RECIPES, YOLOX.model_id, replace(RECIPES[YOLOX.model_id], packages=(missing,)))
    plan = manager.create_plan(YOLOX.model_id)
    assert plan.readiness.state == "blocked" and plan.runtime_snapshot["package:" + missing] == "missing"
    with pytest.raises(ProvisioningConflict, match="dependencies are missing"):
        manager.start(ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash, approved=True))
    assert not requests and not Path(plan.target_directory).exists()


def test_install_active_and_completed_idempotency_and_api_receipt(mocked_install, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    client, manager, contents, requests = mocked_install
    entered, release = Event(), Event()
    def smoke(*args: object) -> dict[str, object]:
        entered.set()
        assert release.wait(3)
        return {"input_sha256": BLACK, "elapsed_s": .001, "observation_count": 0, "execution_identity_hash": "b" * 64}
    monkeypatch.setattr(manager, "_smoke", smoke)
    plan = client.post("/provisioning/plans", json={"model_id": YOLOX.model_id}).json()
    request = {"plan_id": plan["id"], "plan_hash": plan["plan_hash"], "approved": True}
    first = client.post("/provisioning/jobs", json=request).json()
    assert entered.wait(3)
    assert client.post("/provisioning/jobs", json=request).json()["id"] == first["id"]
    assert client.get("/provisioning/jobs", params={"model_id": YOLOX.model_id}).json()[0]["id"] == first["id"]
    release.set()
    result = wait_job(manager, first["id"])
    assert result.status == "completed", result.error
    assert result.result and result.result.installed and result.result.smoke_status == "passed"
    target = Path(result.result.installation_path)
    assert all((target / name).read_bytes() == value for name, value in contents.items())
    assert (target / "provenance.json").is_file() and len(requests) == 2
    assert client.post("/provisioning/jobs", json=request).json()["id"] == first["id"]
    assert len(requests) == 2 and current_health(YOLOX.model_id) is not None
    receipt = client.get("/provisioning/health/" + str(result.result.health_receipt_id)).json()
    assert receipt["quality_claim"] == "none" and receipt["input_sha256"] == BLACK
    assert ProvisioningManager(manager.root.parent).get(result.id).status == "completed"
    if destination := os.environ.get("VISION_PROVISIONING_FIXTURES"):
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        for name, payload in {"options": client.get("/provisioning/options").json(), "plan": plan,
                              "job": result.model_dump(mode="json"), "health": receipt}.items():
            (folder / (name + ".json")).write_text(json.dumps(payload, indent=2) + "\n")


def test_bad_download_is_atomic_and_retry_is_explicit(mocked_install) -> None:  # type: ignore[no-untyped-def]
    _, manager, contents, requests = mocked_install
    plan = manager.create_plan(YOLOX.model_id)
    original = contents["model.onnx"]
    contents["model.onnx"] = b"corrupt"
    approved = ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash, approved=True)
    first = wait_job(manager, manager.start(approved).id)
    assert first.status == "failed" and "SHA256" in (first.error or "")
    assert not Path(plan.target_directory).exists()
    assert not list((Path(plan.target_directory).parent / ".provisioning-staging").iterdir())
    assert len(requests) == 1
    contents["model.onnx"] = original
    second = wait_job(manager, manager.start(approved).id)
    assert second.status == "completed" and second.id != first.id


def test_smoke_failure_keeps_install_unchecked_until_new_explicit_validation(mocked_install, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    _, manager, _, requests = mocked_install
    def failed(*args: object) -> dict[str, object]:
        raise TimeoutError("Explicit mocked inference timeout")
    monkeypatch.setattr(manager, "_smoke", failed)
    plan = manager.create_plan(YOLOX.model_id)
    failed_job = wait_job(manager, manager.start(ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash, approved=True)).id)
    assert failed_job.status == "failed" and failed_job.result and failed_job.result.installed
    assert failed_job.result.smoke_status == "failed" and current_health(YOLOX.model_id) is None
    next_plan = manager.create_plan(YOLOX.model_id)
    assert next_plan.action == "validate" and next_plan.total_download_bytes == 0 and len(requests) == 2
    with pytest.raises(ProvisioningConflict, match="Installation changed"):
        manager.start(ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash, approved=True))


@pytest.mark.parametrize("change", ["target", "runtime", "saved_plan"])
def test_changed_review_cannot_authorize_mutation(mocked_install, monkeypatch: pytest.MonkeyPatch, change: str) -> None:  # type: ignore[no-untyped-def]
    _, manager, _, requests = mocked_install
    plan = manager.create_plan(YOLOX.model_id)
    if change == "target":
        target = Path(plan.target_directory)
        target.mkdir(parents=True)
        (target / "model.onnx").write_bytes(b"Do not overwrite this file")
    elif change == "runtime":
        monkeypatch.setattr("engine.provisioning.manager.runtime_snapshot", lambda _: {"changed": "yes"})
    else:
        path = manager.path("plans", plan.id)
        raw = json.loads(path.read_text())
        raw["target_directory"] = "/outside"
        path.write_text(json.dumps(raw))
    with pytest.raises(ProvisioningConflict, match="changed"):
        manager.start(ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash, approved=True))
    assert not requests


@pytest.mark.parametrize("kind", ["redirect", "oversize", "truncated", "hash", "length", "encoded"])
def test_stream_rejects_unreviewed_or_different_content(tmp_path: Path, kind: str) -> None:
    value = b"known"
    artifact = ProvisioningArtifact(filename="model.onnx", source_url="https://github.com/pinned",
        expected_sha256=hashlib.sha256(value).hexdigest(), expected_bytes=len(value))
    def response(_: httpx.Request) -> httpx.Response:
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        headers = {"Content-Length": "999"} if kind == "length" else {"Content-Encoding": "gzip"} if kind == "encoded" else {}
        data = value + b"!" if kind == "oversize" else value[:-1] if kind == "truncated" else b"wrong" if kind == "hash" else value
        return httpx.Response(200, headers=headers, stream=ByteStream(data))
    path = tmp_path / "part"
    with httpx.Client(transport=httpx.MockTransport(response), follow_redirects=False) as client:
        with pytest.raises(ValueError):
            download_artifact(artifact, path, deadline=time.monotonic() + 2, stopped=Event(), progress=lambda _: None, client=client)
    assert not path.exists()


def test_smoke_capture_is_bounded_and_command_fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    import engine.provisioning.manager as module
    original = subprocess.Popen
    captured = []
    def noisy(command, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(command)
        return original([sys.executable, "-c", "print('x' * 100000)"], **kwargs)
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(module.subprocess, "Popen", noisy)
    manager = ProvisioningManager(tmp_path / "workspace")
    with pytest.raises(ValueError, match="diagnostic bound"):
        manager._smoke(YOLOX.model_id, time.monotonic() + 3)
    assert captured[0] == [sys.executable, "-m", "engine.provisioning.smoke", YOLOX.model_id]


def test_official_manifest_matches_adapter_constants() -> None:
    from engine.models.yolox_config import MODEL_BYTES, MODEL_SHA256, MODEL_URL
    assert YOLOX.artifacts[0].expected_bytes == MODEL_BYTES
    assert YOLOX.artifacts[0].expected_sha256 == MODEL_SHA256
    assert YOLOX.artifacts[0].source_url == MODEL_URL
