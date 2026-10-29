"""Independent bounded-stream, stale-health and crash-recovery software checks."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from filelock import FileLock

import engine.adapters.identity as identity
import engine.capabilities as capabilities
import engine.provisioning.download as download
import engine.provisioning.registry as registry
from engine.provisioning import ProvisioningManager, state
from engine.service import WorkspaceService
from spec.provisioning import (
    ProvisioningArtifact,
    ProvisioningHealth,
    ProvisioningJob,
    ProvisioningJobRequest,
)


@pytest.mark.parametrize("stop_early", [False, True])
def test_small_transport_chunks_enforce_deadline_and_cancellation_before_buffer_fills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_early: bool,
) -> None:
    clock = [0.]
    reads: list[int] = []
    stopped = Event()
    class SlowStream(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(20):
                clock[0] += 1
                reads.append(index)
                if stop_early and index == 1:
                    stopped.set()
                yield b"x"
    def reply(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] <= 1
        return httpx.Response(200, stream=SlowStream())
    monkeypatch.setattr(download.time, "monotonic", lambda: clock[0])
    artifact = ProvisioningArtifact(filename="model.onnx", source_url="https://github.com/test",
        expected_sha256=hashlib.sha256(b"x" * 20).hexdigest(), expected_bytes=20)
    target = tmp_path / "model.onnx"
    with httpx.Client(transport=httpx.MockTransport(reply)) as client, pytest.raises(TimeoutError):
        download.download_artifact(artifact, target, deadline=3, stopped=stopped,
                                   progress=lambda _: None, client=client)
    assert len(reads) == (2 if stop_early else 3)
    assert not target.exists()


def test_health_rechecks_exact_fixed_request_identity_even_if_other_snapshot_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_id = "yolox-s-onnx-coco"
    path = tmp_path / "health.json"
    current = ["a" * 64]
    calls = []
    def resolve(request):
        calls.append(request)
        return SimpleNamespace(identity_hash=current[0], unavailable_artifacts=[])
    monkeypatch.setattr(identity, "resolve_execution_identity", resolve)
    monkeypatch.setattr(state, "health_path", lambda _: path)
    monkeypatch.setattr(state, "installation_matches", lambda _: True)
    monkeypatch.setattr(state, "installation_hash", lambda _: "same-artifacts")
    monkeypatch.setattr(state, "runtime_snapshot", lambda _: {"source": "same-source"})
    receipt = ProvisioningHealth(id="receipt", model_id=model_id, job_id="job", plan_hash="plan",
        created_at="test", installation_hash="same-artifacts", runtime_snapshot={"source": "same-source"},
        input_sha256="0" * 64, elapsed_s=.1, observation_count=0, execution_identity_hash=current[0])
    path.write_text(receipt.model_dump_json())
    assert state.current_health(model_id) == receipt
    current[0] = "b" * 64
    assert state.current_health(model_id) is None
    assert len(calls) == 2
    assert all(request.model_id == model_id and request.classes == ["person"]
               and request.min_conf == .3 for request in calls)


def test_unreadable_worker_job_still_releases_both_leases(tmp_path: Path) -> None:
    manager = ProvisioningManager(tmp_path)
    worker_lease = FileLock(tmp_path / "worker-test.lock", thread_local=False)
    model_lease = FileLock(tmp_path / "model-test.lock", thread_local=False)
    worker_lease.acquire()
    model_lease.acquire()
    try:
        try:
            manager._run("a" * 32, worker_lease, model_lease)
        except (OSError, ValueError):
            pass  # The recovery error may propagate; its locks must never leak.
        assert not worker_lease.is_locked and not model_lease.is_locked
    finally:
        worker_lease.release()
        model_lease.release()
        manager.close()


def test_restart_removes_only_interrupted_jobs_owned_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = tmp_path / "models"
    monkeypatch.setenv("VISION_MODELS_DIR", str(models))
    manager = ProvisioningManager(tmp_path / "data")
    job = ProvisioningJob(id="b" * 32, plan_id="c" * 32, plan_hash="d" * 64,
        model_id="yolox-s-onnx-coco", status="running", phase="downloading",
        created_at="test", updated_at="test", total_bytes=100)
    manager.save_job(job)
    stage = models / ".provisioning-staging" / job.id
    stage.mkdir(parents=True)
    (stage / "model.onnx").write_bytes(b"unfinished")
    unrelated = models / "user-model"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("preserve")
    recovered = ProvisioningManager(tmp_path / "data")
    try:
        assert recovered.get(job.id).status == "interrupted"
        assert not stage.exists()
        assert (unrelated / "keep.txt").read_text() == "preserve"
    finally:
        recovered.close()
        manager.close()


def test_yolox_only_installation_can_validate_its_selected_detector_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkspaceService(tmp_path)
    rows = [
        SimpleNamespace(id="model.owlv2-base-patch16", installation_ready=False, task_types=["detection"],
                        readiness=SimpleNamespace(reason="OWLv2 deliberately not installed")),
        SimpleNamespace(id="model.yolox-s-onnx-coco", installation_ready=True,
                        implemented=True, availability="installed", task_types=["detection"]),
    ]
    monkeypatch.setattr(capabilities, "model_catalog", lambda: rows)
    capabilities.validate_experiment_capabilities(service,
        ["block.frame_sample", "block.detect_open_vocab", "model.yolox-s-onnx-coco"])


def test_new_failed_validation_retires_current_success_but_preserves_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from engine.capabilities.models import _yolox

    model_id = "yolox-s-onnx-coco"
    model_root = tmp_path / "models"
    monkeypatch.setenv("VISION_MODELS_DIR", str(model_root))
    target = model_root / model_id
    target.mkdir(parents=True)
    payload = b"software-test-placeholder-not-an-ONNX-model"
    (target / "model.onnx").write_bytes(payload)
    recipe = registry.Recipe(model_id=model_id, name="Test-only pinned artifact", revision="test",
        artifacts=(ProvisioningArtifact(filename="model.onnx", source_url="https://github.com/test",
            expected_sha256=hashlib.sha256(payload).hexdigest(), expected_bytes=len(payload)),),
        packages=())
    monkeypatch.setitem(registry.RECIPES, model_id, recipe)
    monkeypatch.setattr(registry, "YOLOX", recipe)
    execution_id = "e" * 64
    monkeypatch.setattr(identity, "resolve_execution_identity", lambda _: SimpleNamespace(
        identity_hash=execution_id, unavailable_artifacts=[]))
    manager = ProvisioningManager(tmp_path / "data")
    black_hash = hashlib.sha256(b"RGB\0" + struct.pack(">II", 640, 640)
                               + bytes(640 * 640 * 3)).hexdigest()
    def successful_smoke(*args: object) -> dict[str, object]:
        return {"input_sha256": black_hash, "elapsed_s": .1, "observation_count": 0,
                "execution_identity_hash": execution_id}
    monkeypatch.setattr(manager, "_smoke", successful_smoke)
    try:
        plan = manager.create_plan(model_id)
        assert plan.action == "validate" and not plan.blockers
        first = manager.start(ProvisioningJobRequest(plan_id=plan.id, plan_hash=plan.plan_hash,
                                                     approved=True))
        manager.threads[-1].join(timeout=5)
        assert not manager.threads[-1].is_alive()
        assert manager.get(first.id).status == "completed"
        old_receipt = state.current_health(model_id)
        assert old_receipt is not None and _yolox().callable
        def failing_smoke(*args: object) -> dict[str, object]:
            raise RuntimeError("Test-only new inference failure")
        monkeypatch.setattr(manager, "_smoke", failing_smoke)
        new_plan = manager.create_plan(model_id)
        assert new_plan.runtime_snapshot == plan.runtime_snapshot
        second = manager.start(ProvisioningJobRequest(plan_id=new_plan.id,
            plan_hash=new_plan.plan_hash, approved=True))
        manager.threads[-1].join(timeout=5)
        assert not manager.threads[-1].is_alive()
        failed = manager.get(second.id)
        assert failed.status == "failed" and failed.result is not None
        assert failed.result.smoke_status == "failed" and failed.result.installed
        assert state.current_health(model_id) is None
        assert not _yolox().callable
        assert manager.health(old_receipt.id) == old_receipt
        assert (target / "model.onnx").read_bytes() == payload
    finally:
        manager.close()
