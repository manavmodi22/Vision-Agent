from pathlib import Path

import pytest

from engine.jobs import Job, JobManager
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.models import EvalDataset


def test_training_requires_reviewed_nonfixture_data(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("fixture")
    service.demo(project.id)
    manager = JobManager(service)
    with pytest.raises(ValueError, match="explicit user"):
        manager.start(project.id, 0, 1, 1, False)
    with pytest.raises(ValueError, match="Geometric"):
        manager.start(project.id, 0, 1, 1, True)
    project = service.create_project("empty")
    with pytest.raises(ValueError, match="20 reviewed"):
        manager.start(project.id, 0, 1, 1, True)
    with pytest.raises(ValueError, match="5 minutes"):
        manager.start(project.id, 0, 10, 1, True)


def test_interrupted_training_is_never_reported_as_success(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("restart")
    manager = JobManager(service)
    job = Job(id="a" * 32, status="running", progress=0.3)
    atomic_model(manager.path(project.id, job.id), job)
    restored = JobManager(WorkspaceService(tmp_path)).get(project.id, job.id)
    assert restored.status == "interrupted"
    assert restored.error and restored.result is None


def test_frozen_holdout_retains_full_annotation_pool(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("holdout")
    service.demo(project.id)
    original = service.annotations(project.id)
    holdout = EvalDataset(id="holdout", annotations=original.annotations[-10:])
    atomic_model(service.root(project.id) / "active-holdout.json", holdout)
    assert len(service.annotations(project.id).annotations) == 16
    assert len(service.evaluation_annotations(project.id).annotations) == 10
    original.annotations[-1].reviewed = False
    service.save_annotations(project.id, original)
    assert not service.evaluation_annotations(project.id).annotations[-1].reviewed
    assert len(service.annotations(project.id).annotations) == 16


def test_live_worker_lease_prevents_false_interruption(tmp_path: Path) -> None:
    from filelock import FileLock
    service = WorkspaceService(tmp_path)
    project = service.create_project("active job")
    manager = JobManager(service)
    job = Job(id="b" * 32, status="running", progress=0.3)
    atomic_model(manager.path(project.id, job.id), job)
    with FileLock(tmp_path / ".training.lock", timeout=0):
        second = JobManager(WorkspaceService(tmp_path))
        assert second.get(project.id, job.id).status == "running"


def test_training_setup_failure_releases_both_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from filelock import FileLock
    from PIL import Image

    import engine.jobs as job_module
    from agent.templates import build_template
    from spec.models import Annotation, Detection
    service = WorkspaceService(tmp_path)
    project = service.create_project("setup failure")
    annotations = []
    for index in range(20):
        path = service.root(project.id) / f"image-{index}.png"
        Image.new("RGB", (10, 10), (index, 50, 100)).save(path)
        annotations.append(Annotation(image_path=str(path), reviewed=True,
            detections=[Detection(label="person", confidence=1, box=[0, 0, 1, 1])]))
    atomic_model(service.root(project.id) / "annotations.json", EvalDataset(id="reviewed", annotations=annotations))
    project.candidates = build_template("damage", "media", "owlv2-base-patch16")
    service.repository.save(project)
    manager = JobManager(service)

    def missing_evidence(*args: object) -> str:
        raise ValueError("Evidence disappeared")

    monkeypatch.setattr(job_module, "dataset_hash", missing_evidence)
    with pytest.raises(ValueError, match="disappeared"):
        manager.start(project.id, 0, 1, 1, True)
    assert manager.worker_lock.acquire(blocking=False)
    manager.worker_lock.release()
    with FileLock(tmp_path / ".training.lock", timeout=0):
        pass


def test_current_holdout_preserves_frozen_order_and_fingerprint(tmp_path: Path) -> None:
    from engine.eval import dataset_hash
    service = WorkspaceService(tmp_path)
    project = service.create_project("ordered holdout")
    service.demo(project.id)
    full = service.annotations(project.id)
    holdout = EvalDataset(id="heldout", annotations=list(reversed(full.annotations[-10:])))
    atomic_model(service.root(project.id) / "active-holdout.json", holdout)
    actual = service.evaluation_annotations(project.id)
    assert [a.image_path for a in actual.annotations] == [a.image_path for a in holdout.annotations]
    assert dataset_hash(actual, service.root(project.id)) == dataset_hash(holdout.model_copy(update={"id": full.id}), service.root(project.id))


def test_training_uses_reviewed_subset_and_selected_holdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    import engine.train
    from agent.templates import build_template
    from spec.models import Annotation, Detection

    service = WorkspaceService(tmp_path)
    project = service.create_project("Mixed review pool", "custom")
    rows = []
    media = service.root(project.id) / "media"
    media.mkdir()
    for index in range(25):
        path = media / f"image-{index}.png"
        Image.new("RGB", (12, 10), (index, 40, 80)).save(path)
        rows.append(Annotation(image_path=str(path), reviewed=index < 20,
            detections=[Detection(label="person", confidence=1, box=[.1, .1, .8, .8])]))
    project.media = [a.image_path for a in rows]
    project.candidates = build_template("custom", "media", "owlv2-base-patch16", classes=["person"])
    service.repository.save(project)
    atomic_model(service.root(project.id) / "annotations.json", EvalDataset(id="pool", annotations=rows))
    selected = rows[:10]
    atomic_model(service.root(project.id) / "active-holdout.json", EvalDataset(id="validation", annotations=selected))
    observed: list[tuple[EvalDataset, EvalDataset]] = []

    def capture_split(training: EvalDataset, evaluation: EvalDataset, *args: object, **kwargs: object) -> None:
        observed.append((training, evaluation))
        raise ValueError("Stop after verifying the data boundary")

    monkeypatch.setattr(engine.train, "train_detector", capture_split)
    manager = JobManager(service)
    job = manager.start(project.id, 0, 1, 1, True)
    manager.threads[job.id].join(timeout=5)
    assert len(observed) == 1
    training, evaluation = observed[0]
    assert [a.image_path for a in training.annotations] == [a.image_path for a in rows[10:20]]
    assert [a.image_path for a in evaluation.annotations] == [a.image_path for a in selected]
    assert len(service.annotations(project.id).annotations) == 25


def test_human_training_never_consumes_reserved_acceptance_groups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image

    import engine.train
    from agent.templates import build_template
    from engine.eval.protocol import read_configuration, save_configuration
    from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment
    from spec.models import Annotation, Detection

    service = WorkspaceService(tmp_path)
    project = service.create_project("Training split software test", "custom")
    root = service.root(project.id)
    (root / "media").mkdir()
    rows = []
    for index in range(30):
        path = root / "media" / f"sample-{index:02}.png"
        Image.new("RGB", (12, 10), (index * 7, 40, 80)).save(path)
        rows.append(Annotation(image_path=str(path), reviewed=True,
            detections=[Detection(label="person", confidence=1, box=[.1, .1, .8, .8])]))
    project.media = [row.image_path for row in rows]
    project.candidates = build_template("custom", "media", "owlv2-base-patch16", classes=["person"])
    service.repository.save(project)
    dataset = EvalDataset(id="split-test", annotations=rows)
    atomic_model(root / "annotations.json", dataset)
    config = read_configuration(root, dataset)
    assignments = [EvidenceAssignment(image_path=row.image_path,
        scene_group="development" if index < 10 else "validation" if index < 20 else "reserved",
        split="train" if index < 10 else "validation" if index < 20 else "acceptance")
        for index, row in enumerate(config.images)]
    save_configuration(root, dataset, EvaluationConfigurationUpdate(expected_revision=config.revision,
        assignments=assignments, policy=config.policy))
    observed: list[tuple[EvalDataset, EvalDataset]] = []
    def capture(training: EvalDataset, evaluation: EvalDataset, *args: object, **kwargs: object) -> None:
        observed.append((training, evaluation))
        raise ValueError("Software split assertion; no model constructed")
    monkeypatch.setattr(engine.train, "train_detector", capture)
    manager = JobManager(service)
    job = manager.start(project.id, 0, 1, 1, True)
    manager.threads[job.id].join(timeout=10)
    assert observed, manager.get(project.id, job.id).error
    training, validation = observed[0]
    assert {row.image_path for row in training.annotations} == {row.image_path for row in rows[:10]}
    assert {row.image_path for row in validation.annotations} == {row.image_path for row in rows[10:20]}
    assert service.annotations(project.id) == dataset
    after = read_configuration(root, dataset)
    assert all("training" not in row.exposure_reasons and "training_validation" not in row.exposure_reasons
               for row in after.images if row.split == "acceptance")
