"""Approved job provenance with mocked optimization/scoring; never an accuracy test."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.templates import build_template
from engine.eval import dataset_hash, spec_hash
from engine.jobs import JobManager
from engine.models.local_manifest import LocalDetectorManifest, read_manifest
from engine.platform.model_registration import register_user_candidate
from engine.platform.planning_options import planning_options
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from engine.train.contracts import TrainingResult
from spec.models import Annotation, Detection, EvalDataset, EvaluationResult


def write_model(root: Path, identifier: str, training: str = "a" * 64, evaluation: str = "b" * 64) -> Path:
    path = root / identifier
    path.mkdir(parents=True)
    record = LocalDetectorManifest(id=identifier, classes=["person"], training_hash=training,
        evaluation_hash=evaluation, created_at="2026-10-28", training_samples=10,
        epochs_completed=1, steps=5, final_loss=1)
    atomic_model(path / "manifest.json", record)
    (path / "model.safetensors").write_bytes(b"Metadata fixture only; never loaded")
    return path


def setup_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[WorkspaceService, str, Path]:
    models = tmp_path / "models"
    monkeypatch.setenv("VISION_MODELS_DIR", str(models))
    write_model(models, "local-existing")
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Approved registration control-plane test", "custom")
    media = service.root(project.id) / "media"
    media.mkdir()
    rows = []
    for index in range(20):
        path = media / f"image-{index}.png"
        Image.new("RGB", (8, 8), (index, 40, 80)).save(path)
        rows.append(Annotation(image_path=str(path), reviewed=True,
            detections=[Detection(label="person", confidence=1, box=[0, 0, 1, 1])]))
    project.media = [row.image_path for row in rows]
    project.candidates = build_template("custom", "media", "local-existing", classes=["person"])
    service.repository.save(project)
    atomic_model(service.root(project.id) / "annotations.json", EvalDataset(id="test-reviewed", annotations=rows))
    return service, project.id, models


def result_for(path: Path, training_hash: str, evaluation_hash: str) -> TrainingResult:
    return TrainingResult(model_id=path.name, model_path=str(path), classes=["person"], epochs_completed=1,
        steps=5, elapsed_s=0, final_loss=1, training_samples=10, evaluation_samples=10,
        training_hash=training_hash, evaluation_hash=evaluation_hash, device="cpu", warnings=["Mock optimizer result; no inference"])


def test_approved_job_records_purpose_before_scoring_without_quality_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.train

    service, project_id, models = setup_project(tmp_path, monkeypatch)
    original = (models / "local-existing" / "manifest.json").read_bytes()
    trained: list[str] = []
    scored: list[int] = []

    def fake_train(training: EvalDataset, evaluation: EvalDataset, project_root: Path, model_id: str, **kwargs: object) -> TrainingResult:
        training_fingerprint, evaluation_fingerprint = dataset_hash(training, project_root), dataset_hash(evaluation, project_root)
        path = write_model(models, model_id, training_fingerprint, evaluation_fingerprint)
        trained.append(model_id)
        return result_for(path, training_fingerprint, evaluation_fingerprint)

    def fake_score(identifier: str, candidate_index: int = 0) -> EvaluationResult:
        candidate = service.candidate(identifier, candidate_index)
        if candidate_index:
            record = read_manifest(trained[0], models)
            assert record.use_scope == "user_candidate" and record.use_scope_evidence_ref
        scored.append(candidate_index)
        return EvaluationResult(precision=0, recall=0, count_mae=10, passed=False,
            metric=candidate.eval.metric, target=candidate.eval.target, sample_count=10,
            spec_hash=spec_hash(candidate, service.root(identifier)),
            dataset_hash=dataset_hash(service.evaluation_annotations(identifier), service.root(identifier)))

    monkeypatch.setattr(engine.train, "train_detector", fake_train)
    monkeypatch.setattr(service, "evaluate", fake_score)
    manager = JobManager(service)
    with pytest.raises(ValueError, match="explicit user"):
        manager.start(project_id, 0, 1, 1, False)
    assert not trained
    job = manager.start(project_id, 0, 1, 1, True)
    manager.threads[job.id].join(timeout=10)
    completed = manager.get(project_id, job.id)
    assert completed.status == "completed", completed.error
    assert scored == [0, 1] and completed.result
    proof = completed.result["registration"]
    assert isinstance(proof, dict) and proof["quality_status"] == "unassessed"
    assert proof["evidence_ref"] == f"training-job:{project_id}:{job.id}"
    assert read_manifest(trained[0], models).use_scope == "user_candidate"
    assert read_manifest(trained[0], models).training_state == "optimization_completed"
    assert read_manifest(trained[0], models).initialization == "unknown"
    assert trained[0] in {entry.model_id for entry in planning_options(service, project_id).eligible_models}
    assert (models / "local-existing" / "manifest.json").read_bytes() == original
    assert service.get_project(project_id).deployment_id is None
    assert not service.events(project_id)


def test_preexisting_output_is_never_reclassified_or_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.jobs as jobs
    import engine.train

    service, project_id, models = setup_project(tmp_path, monkeypatch)
    existing = write_model(models, "local-detector-aaaaaaaaaaaa")
    before = (existing / "manifest.json").read_bytes()
    monkeypatch.setattr(jobs, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="a" * 32)))
    monkeypatch.setattr(engine.train, "train_detector", lambda *args, **kwargs: pytest.fail("Existing output must stop before optimization"))
    manager = JobManager(service)
    job = manager.start(project_id, 0, 1, 1, True)
    manager.threads[job.id].join(timeout=10)
    stopped = manager.get(project_id, job.id)
    assert stopped.status == "failed" and "already exists" in (stopped.error or "")
    assert (existing / "manifest.json").read_bytes() == before
    assert len(service.get_project(project_id).candidates) == 1


@pytest.mark.parametrize("field", ["training_hash", "evaluation_hash", "model_id", "backend", "base_model_id"])
def test_mismatched_output_receipt_never_changes_registration(tmp_path: Path, field: str) -> None:
    path = write_model(tmp_path, "local-new")
    output = result_for(path, "a" * 64, "b" * 64)
    changed = "local-other" if field in {"model_id", "base_model_id"} else "rtdetr-v2-r18" if field == "backend" else "c" * 64
    output = output.model_copy(update={field:changed})
    before = (path / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="different|does not match"):
        register_user_candidate(output, "local-new", path, "a" * 64, "b" * 64, "job:test")
    assert (path / "manifest.json").read_bytes() == before
