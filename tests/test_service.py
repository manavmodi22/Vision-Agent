from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agent.templates import build_template
from engine.api import create_app
from engine.service import WorkspaceService
from engine.store.models import Settings


def prepared(root: Path) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(root)
    project = service.create_project("Integration walkthrough", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1"), "Count pallets")
    return service, project.id


def test_complete_workflow_and_restart(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path)
    preview = service.preview(identifier)
    assert len(preview.frames) == 5
    with pytest.raises(ValueError, match="Approve deployment"):
        service.run(identifier)
    result = service.evaluate(identifier)
    assert result.passed and result.sample_count == 16
    with pytest.raises(ValueError, match="explicit user"):
        service.deploy(identifier, 0, False)
    service.deploy(identifier, 0, True, "Isolated synthetic software trial", approval_scope="local_trial")
    resumed = WorkspaceService(tmp_path)
    actual = resumed.run(identifier, max_frames=3)
    assert len(actual.frames) == 3
    events = resumed.events(identifier)
    assert events and all(event.payload["synthetic"] for event in events)
    crops = [event for event in events if event.crop_path]
    assert crops and all(Path(event.crop_path).is_file() for event in crops)


def test_label_edits_revoke_approval(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path)
    service.evaluate(identifier)
    service.deploy(identifier, 0, True, "Isolated synthetic software trial", approval_scope="local_trial")
    annotations = service.annotations(identifier)
    annotations.annotations[0].reviewed = False
    service.save_annotations(identifier, annotations)
    assert service.get_project(identifier).deployment_id is None
    with pytest.raises(ValueError, match="Evaluate this"):
        service.deploy(identifier, 0, True, "I approve anyway", approval_scope="local_trial")
    # A new validation protocol may select only the remaining reviewed rows.
    assert service.evaluate(identifier).sample_count == 15


def test_media_bytes_and_zone_edits_reject_stale_evidence(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path)
    service.evaluate(identifier)
    zone_path = service.root(identifier) / "zones/lanes.json"
    zone_path.write_text(zone_path.read_text().replace('"A"', '"New A"'))
    with pytest.raises(ValueError, match="Evaluate this"):
        service.deploy(identifier, 0, True)
    service.evaluate(identifier)
    image_path = Path(service.get_project(identifier).media[0])
    Image.new("RGB", (640, 400)).save(image_path)
    with pytest.raises(ValueError, match="Evaluate this|Media changed"):
        service.deploy(identifier, 0, True)


def test_override_requires_real_evaluation_and_reason(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path)
    with pytest.raises(ValueError, match="Evaluate this"):
        service.deploy(identifier, 0, True, "Explicit override")
    dataset = service.annotations(identifier)
    for annotation in dataset.annotations:
        annotation.detections = []
    service.save_annotations(identifier, dataset)
    assert not service.evaluate(identifier).passed
    with pytest.raises(ValueError, match="Promotion requires"):
        service.deploy(identifier, 0, True)
    response = service.deploy(identifier, 0, True, "Reviewed false positives; synthetic test only", approval_scope="local_trial")
    assert response["status"] == "ready"


def test_project_isolation_and_path_rejection(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path)
    with pytest.raises(ValueError, match="identifier"):
        service.get_project("../secrets")
    dataset = service.annotations(identifier)
    dataset.annotations[0].image_path = "/etc/passwd"
    with pytest.raises(ValueError, match="imported image"):
        service.save_annotations(identifier, dataset)
    second = service.create_project("Independent")
    assert not service.events(second.id)


def test_api_walkthrough_and_wire_aliases(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    project = client.post("/projects", json={"name": "API example"}).json()
    identifier = project["id"]
    assert client.post(f"/projects/{identifier}/demo").status_code == 200
    planned = client.post(f"/projects/{identifier}/plan", json={"mode": "template", "model": "fixture-color-v1"})
    assert planned.status_code == 200, planned.text
    assert "in" in planned.json()["candidates"][0]["blocks"][0]
    got = client.get(f"/projects/{identifier}").json()
    assert "in" in got["candidates"][0]["blocks"][0]
    assert client.post(f"/projects/{identifier}/evaluate", json={}).json()["passed"]
    assert client.post(f"/projects/{identifier}/deploy", json={"approved": False}).status_code == 400
    assert client.post(f"/projects/{identifier}/deploy", json={"approved": True, "approval_scope": "local_trial", "override_reason": "Isolated API software trial"}).status_code == 200
    assert client.post(f"/projects/{identifier}/run", json={"max_frames": 1}).status_code == 200
    assert client.get(f"/projects/{identifier}/events.csv").text.startswith("id,created_at")
    answer = client.post(f"/projects/{identifier}/ask", json={"question": "How many pallets today?"})
    assert answer.status_code == 400
    assert "model" in answer.json()["detail"].lower()


def test_remote_model_urls_rejected() -> None:
    for url in ("https://example.com/v1", "http://localhost.evil.test/v1", "http://user:pass@localhost/v1"):
        with pytest.raises(ValueError):
            Settings(model_url=url)


def test_evidence_changes_during_run_do_not_persist_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.service as service_module
    from spec.models import PipelineSpec, RunResult
    service, identifier = prepared(tmp_path)
    service.evaluate(identifier)
    service.deploy(identifier, 0, True, "Isolated synthetic software trial", approval_scope="local_trial")
    real_run = service_module.run_pipeline

    def changed_run(spec: PipelineSpec, root: Path, max_frames: int = 50) -> RunResult:
        result = real_run(spec, root, max_frames=max_frames)
        image = Path(service.get_project(identifier).media[0])
        Image.new("RGB", (640, 400)).save(image)
        return result

    monkeypatch.setattr(service_module, "run_pipeline", changed_run)
    with pytest.raises(ValueError, match="changed|stale"):
        service.run(identifier, max_frames=2)
    assert service.events(identifier) == []


def test_approved_pipeline_runs_new_media_without_changing_dataset(tmp_path: Path) -> None:
    from engine.eval import dataset_hash
    service, identifier = prepared(tmp_path / "workspace")
    service.evaluate(identifier)
    service.deploy(identifier, 0, True, "Isolated synthetic software trial", approval_scope="local_trial")
    original = service.get_project(identifier)
    original_labels = dataset_hash(service.annotations(identifier), service.root(identifier))
    outside = tmp_path / "production.png"
    Image.new("RGB", (640, 400), "black").save(outside)
    run = service.run(identifier, max_frames=1, paths=[str(outside)])
    assert len(run.frames) == 1
    assert "/runs/" in run.frames[0].image_path and Path(run.frames[0].image_path).is_file()
    after = service.get_project(identifier)
    assert after.media == original.media and after.deployment_id == original.deployment_id
    assert dataset_hash(service.annotations(identifier), service.root(identifier)) == original_labels
    folders = list((service.root(identifier) / "runs").iterdir())
    assert len(folders) == 1 and (folders[0] / "provenance.json").is_file()
    assert (folders[0] / "result.json").is_file()


def test_new_media_run_rejects_stale_approval(tmp_path: Path) -> None:
    service, identifier = prepared(tmp_path / "workspace")
    service.evaluate(identifier)
    service.deploy(identifier, 0, True, "Isolated synthetic software trial", approval_scope="local_trial")
    labels = service.annotations(identifier)
    labels.annotations[0].reviewed = False
    service.save_annotations(identifier, labels)
    with pytest.raises(ValueError, match="Approve deployment"):
        service.run(identifier, paths=[str(tmp_path / "never-opened.png")])
    assert not (service.root(identifier) / "runs").exists()
