"""Complete-label transfers preserve identity and fail before changing labels."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from engine.api import create_app
from engine.dataset_archive import LabelArchiveService
from engine.datasets import DatasetClass, DatasetConflict, DatasetService
from engine.eval.configuration import _read_configuration
from engine.eval.usage import exposure_map, mark_usage
from engine.service import WorkspaceService
from spec.models import Annotation, Detection


def projects(tmp_path: Path) -> tuple[WorkspaceService, DatasetService, str, str, Path]:
    originals = tmp_path / "images"
    originals.mkdir()
    first = originals / "first.png"
    Image.new("RGB", (100, 80), (10, 25, 40)).save(first)
    Image.new("RGB", (120, 90), (80, 50, 30)).save(originals / "second.png")
    service = WorkspaceService(tmp_path / "workspace")
    source = service.create_project("Source labels")
    target = service.create_project("Destination labels")
    service.import_media(source.id, [str(originals)])
    service.import_media(target.id, [str(originals)])
    return service, DatasetService(service), source.id, target.id, first


def archive_file(service: WorkspaceService, source: str, tmp_path: Path) -> Path:
    exported = LabelArchiveService(service).export_labels(source)
    path = tmp_path / "all.vision-labels.json"
    path.write_text(exported.model_dump_json())
    return path


def labels(service: WorkspaceService, project: str) -> bytes:
    return (service.root(project) / "annotations.json").read_bytes()


def test_complete_label_transfer_resets_review_and_preserves_other_images(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    manifest = datasets.manifest(source)
    datasets.save_classes(source, manifest.revision, [DatasetClass(id="part", name="part", color="#123456")])
    rows = service.annotations(source)
    rows.annotations[0].detections = [Detection(label="part", confidence=1, box=[.1, .2, .8, .9])]
    rows.annotations[0].expected_texts = ["X", "Х", "X"]
    service.save_annotations(source, rows)
    rows = service.annotations(source)
    rows.annotations[0].reviewed = True
    service.save_annotations(source, rows)
    exported = archive_file(service, source, tmp_path)
    extra = tmp_path / "extra.png"
    Image.new("RGB", (70, 60), (99, 40, 20)).save(extra)
    service.import_media(target, [str(extra)])
    target_rows = service.annotations(target)
    target_rows.annotations[-1].expected_texts = ["preserve"]
    service.save_annotations(target, target_rows)
    result = LabelArchiveService(service).import_labels(target, str(exported), datasets.manifest(target).revision)
    actual = service.annotations(target)
    assert len(actual.annotations) == 3 and not any(row.reviewed for row in actual.annotations)
    assert actual.annotations[0].expected_texts == ["X", "Х", "X"]
    assert actual.annotations[0].detections[0].box == [.1, .2, .8, .9]
    assert actual.annotations[-1].expected_texts == ["preserve"]
    assert result.classes[0].name == "part" and result.classes[0].color == "#123456"


@pytest.mark.parametrize("failure", ["missing", "ambiguous", "dimensions", "version", "path", "hash",
                                     "omitted_history", "omitted_version", "omitted_labels"])
def test_bad_archive_never_changes_labels(tmp_path: Path, failure: str) -> None:
    service, datasets, source, target, first = projects(tmp_path)
    path = archive_file(service, source, tmp_path)
    data = json.loads(path.read_text())
    if failure == "missing":
        data["images"][0]["pixels_sha256"] = "f" * 64
    elif failure == "ambiguous":
        service.import_media(target, [str(first)])
    elif failure == "dimensions":
        data["images"][0]["width"] += 1
    elif failure == "version":
        data["schema_version"] = "99"
    elif failure == "path":
        data["images"][0]["file_name"] = "../outside.png"
    elif failure == "hash":
        data["images"][0]["image_sha256"] = "not-a-hash"
    elif failure == "omitted_history":
        del data["images"][0]["model_exposure_reasons"]
    elif failure == "omitted_version":
        del data["schema_version"]
    else:
        del data["images"][0]["annotation"]["text_regions"]
    path.write_text(json.dumps(data))
    before = labels(service, target)
    with pytest.raises(ValueError):
        LabelArchiveService(service).import_labels(target, str(path), datasets.manifest(target).revision)
    assert labels(service, target) == before
    assert not (service.root(target) / "evaluation/usage.json").exists()


def test_stale_revision_and_replace_policy(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    path = archive_file(service, source, tmp_path)
    old = datasets.manifest(target).revision
    rows = service.annotations(target)
    rows.annotations[0].expected_texts = ["keep"]
    service.save_annotations(target, rows)
    archive = LabelArchiveService(service)
    before = labels(service, target)
    with pytest.raises(DatasetConflict, match="Dataset changed"):
        archive.import_labels(target, str(path), old, True)
    revision = datasets.manifest(target).revision
    with pytest.raises(DatasetConflict, match="replacement explicitly"):
        archive.import_labels(target, str(path), revision)
    assert labels(service, target) == before
    archive.import_labels(target, str(path), revision, True)
    assert service.annotations(target).annotations[0].expected_texts == []


def test_exposure_survives_transfer_without_current_seed(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    original = service.annotations(source).annotations[0].image_path
    mark_usage(service.root(source), [original], "deleted_model_seed")
    path = archive_file(service, source, tmp_path)
    archive = json.loads(path.read_text())
    assert archive["images"][0]["model_exposure_reasons"]
    LabelArchiveService(service).import_labels(target, str(path), datasets.manifest(target).revision)
    root = service.root(target)
    configuration = _read_configuration(root, service.annotations(target))
    reasons = exposure_map(root, configuration.images)
    assert any("deleted_model_seed" in reason for value in reasons.values() for reason in value)
    assert not any(row.reviewed for row in service.annotations(target).annotations)


def test_http_export_and_import(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    client = TestClient(create_app(service.repository.root))
    export = client.get(f"/projects/{source}/dataset/export-labels")
    assert export.status_code == 200 and export.json()["schema_version"] == "1"
    path = tmp_path / "api.vision-labels.json"
    path.write_bytes(export.content)
    response = client.post(f"/projects/{target}/dataset/import-labels", json={
        "path": str(path), "base_revision": datasets.manifest(target).revision, "replace_existing": False})
    assert response.status_code == 200 and len(response.json()["images"]) == 2


def test_filename_does_not_authorize_foreign_image_and_encoding_is_irrelevant(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    path = archive_file(service, source, tmp_path)
    # Same normalized pixels with different PNG encoding are a legitimate transfer.
    image = Path(service.annotations(target).annotations[0].image_path)
    with Image.open(image) as frame:
        frame.convert("RGB").save(image, compress_level=0)
    data = json.loads(path.read_text())
    data["images"][0]["file_name"] = "arbitrary-renamed-file.png"
    data["images"][0]["annotation"]["image_path"] = "arbitrary-renamed-file.png"
    path.write_text(json.dumps(data))
    LabelArchiveService(service).import_labels(target, str(path), datasets.manifest(target).revision)
    assert service.annotations(target).annotations[0].image_path == str(image)


def test_region_geometry_and_literal_transcripts_roundtrip(tmp_path: Path) -> None:
    service, datasets, source, target, _ = projects(tmp_path)
    rows = service.annotations(source)
    value = rows.annotations[0].model_dump(mode="json")
    value.update(text_regions=[
        {"id": "region-a", "polygon": [[.1, .2], [.8, .15], [.75, .5], [.15, .55]], "transcript": "ХABC-990Y"},
        {"id": "region-b", "polygon": [[.1, .6], [.4, .6], [.4, .8], [.1, .8]], "transcript": "XABC-990Y"},
        {"id": "region-c", "polygon": [[.5, .6], [.8, .6], [.8, .8], [.5, .8]], "transcript": "XABC-990Y"},
    ], expected_text_source="regions")
    rows.annotations[0] = Annotation.model_validate(value)
    service.save_annotations(source, rows)
    path = archive_file(service, source, tmp_path)
    LabelArchiveService(service).import_labels(target, str(path), datasets.manifest(target).revision)
    imported = service.annotations(target).annotations[0]
    original = service.annotations(source).annotations[0]
    assert imported.text_regions == original.text_regions
    assert imported.expected_text_source == "regions"
    assert imported.expected_texts == ["ХABC-990Y", "XABC-990Y", "XABC-990Y"]
    assert not imported.reviewed
    assert datasets.manifest(target).images[0].text_region_count == 3


def test_image_changed_during_import_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.dataset_archive as archives

    service, datasets, source, target, _ = projects(tmp_path)
    path = archive_file(service, source, tmp_path)
    original = archives._stable_identity
    changed = Path(service.annotations(target).annotations[0].image_path)

    def mutate(root: Path, image: Path) -> dict[str, str]:
        result = original(root, image)
        if image == changed:
            Image.new("RGB", (100, 80), (123, 45, 67)).save(image)
        return result

    monkeypatch.setattr(archives, "_stable_identity", mutate)
    before = labels(service, target)
    with pytest.raises(ValueError, match="Image changed"):
        LabelArchiveService(service).import_labels(target, str(path), datasets.manifest(target).revision)
    assert labels(service, target) == before
