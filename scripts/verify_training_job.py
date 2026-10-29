"""Explicit integration smoke on published GT, isolated from app approvals."""
import json
import time
from pathlib import Path

from engine.jobs import JobManager
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.models import EvalDataset


def main() -> None:
    source_service = WorkspaceService(Path.home() / "Library/Application Support/VisionApp")
    source = next(p for p in source_service.list_projects() if p.name == "NVIDIA warehouse · annotated synthetic")
    truth = source_service.annotations(source.id).annotations[:20]
    root = Path(".visionapp/training-job-verification").resolve()
    service = WorkspaceService(root)
    project = service.create_project("Published synthetic GT job verification")
    project = service.import_media(project.id, [item.image_path for item in truth])
    labels = [item.model_copy(update={"image_path": path, "reviewed": True})
              for item, path in zip(truth, project.media, strict=True)]
    service.save_annotations(project.id, EvalDataset(id="published-gt-job-smoke", annotations=labels))
    service.save_candidates(project.id, source.candidates, "Published GT integration test only")
    manager = JobManager(service)
    job = manager.start(project.id, 0, 1, 1, True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = manager.get(project.id, job.id)
        if job.status in {"completed", "failed", "interrupted"}:
            break
        time.sleep(1)
    destination = Path("artifacts/vision-verification")
    atomic_model(destination / "training-job.json", job)
    assert job.status == "completed", job.model_dump_json()
    actual = service.get_project(project.id)
    assert actual.deployment_id is None
    assert len(actual.candidates) == 2
    assert len(service.annotations(project.id).annotations) == 20
    assert len(service.evaluation_annotations(project.id).annotations) == 10
    assert len(actual.evaluations) == 2
    (destination / "training-job-checks.json").write_text(json.dumps({
        "status": "passed", "full_labels_preserved": 20, "holdout_count": 10,
        "candidates_scored": 2, "automatic_deployment": False,
        "source": "published NVIDIA synthetic GT; isolated verification workspace",
    }, indent=2))
    print(job.status, job.message)


if __name__ == "__main__":
    main()
