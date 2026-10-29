import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from engine.api import create_app
from engine.datasets import DatasetClass, DatasetConflict, DatasetService
from engine.service import WorkspaceService
from spec.models import Detection


def real_dataset(tmp_path: Path, count: int = 2) -> tuple[WorkspaceService, DatasetService, str]:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(count):
        Image.new("RGB", (100, 80), (index, 30, 100)).save(source / f"image-{index}.png")
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("User's objects")
    service.import_media(project.id, [str(source)])
    return service, DatasetService(service), project.id


def test_image_edit_cas_class_rename_and_review(tmp_path: Path) -> None:
    service, datasets, project = real_dataset(tmp_path)
    manifest = datasets.manifest(project)
    manifest = datasets.save_classes(project, manifest.revision,
        [DatasetClass(id="cap", name="bottle cap", color="#123ABC")])
    identifier = manifest.images[0].id
    opened = datasets.image(project, identifier)
    opened.annotation.detections = [Detection(label="bottle cap", confidence=1, box=[.1, .2, .7, .8])]
    opened.annotation.reviewed = True
    saved = datasets.save_image(project, identifier, opened.revision, opened.annotation)
    assert saved.revision > opened.revision
    with pytest.raises(DatasetConflict):
        datasets.save_image(project, identifier, opened.revision, opened.annotation)
    with pytest.raises(ValueError, match="reassign"):
        datasets.save_classes(project, saved.revision, [])
    renamed = datasets.save_classes(project, saved.revision,
        [DatasetClass(id="cap", name="missing cap", color="#ABC123")])
    reloaded = datasets.image(project, identifier).annotation
    assert reloaded.detections[0].label == "missing cap"
    assert not reloaded.reviewed
    assert len(service.annotations(project).annotations) == 2
    assert renamed.classes[0].id == "cap"


def test_large_pool_with_separate_reviewed_holdout(tmp_path: Path) -> None:
    service, datasets, project = real_dataset(tmp_path, 55)
    assert len(datasets.manifest(project).images) == 55
    annotations = service.annotations(project)
    for row in annotations.annotations[:10]:
        row.reviewed = True
    service.save_annotations(project, annotations)
    manifest = datasets.manifest(project)
    selected = [i.id for i in manifest.images[:10]]
    frozen = datasets.freeze_holdout(project, selected)
    assert sum(i.split == "validation" for i in frozen.images) == 10
    assert sum(i.split == "train" for i in frozen.images) == 45
    assert len(service.evaluation_annotations(project).annotations) == 10
    annotations.annotations.pop()
    with pytest.raises(ValueError, match="preserve every"):
        service.save_annotations(project, annotations)


def test_coco_roundtrip_and_immutable_version(tmp_path: Path) -> None:
    service, datasets, project = real_dataset(tmp_path)
    manifest = datasets.manifest(project)
    manifest = datasets.save_classes(project, manifest.revision,
        [DatasetClass(id="widget", name="widget", color="#123456")])
    opened = datasets.image(project, manifest.images[0].id)
    opened.annotation.detections = [Detection(label="widget", confidence=1, box=[.1, .2, .5, .7])]
    opened.annotation.reviewed = True
    datasets.save_image(project, manifest.images[0].id, opened.revision, opened.annotation)
    version = datasets.create_version(project, "Before retraining")
    folder = service.root(project) / "dataset-versions" / version.id
    original_bytes = (folder / "images" / Path(manifest.images[0].image_path).name).read_bytes()
    Image.new("RGB", (100, 80), "red").save(manifest.images[0].image_path)
    assert (folder / "images" / Path(manifest.images[0].image_path).name).read_bytes() == original_bytes
    destination = service.create_project("Imported version")
    imported = datasets.import_coco(destination.id, str(folder / "coco.json"))
    assert len(imported.images) == 2 and sum(i.annotation_count for i in imported.images) == 1
    assert not any(i.reviewed for i in imported.images)
    detection = service.annotations(destination.id).annotations[0].detections[0]
    assert detection.label == "widget" and detection.box == pytest.approx([.1, .2, .5, .7])
    assert datasets.versions(project)[0].reviewed_count == 1


def test_invalid_coco_leaves_project_unchanged(tmp_path: Path) -> None:
    service, datasets, project = real_dataset(tmp_path)
    filename = tmp_path / "invalid.json"
    document = {"images": [{"id": 1, "file_name": "../outside.png", "width": 100, "height": 80}],
                "categories": [{"id": 1, "name": "box"}], "annotations": []}
    filename.write_text(json.dumps(document))
    before = service.get_project(project).model_dump_json()
    with pytest.raises(ValueError, match="relative paths"):
        datasets.import_coco(project, str(filename))
    assert service.get_project(project).model_dump_json() == before


def test_image_route_returns_conflict_without_lost_labels(tmp_path: Path) -> None:
    service, datasets, project = real_dataset(tmp_path)
    client = TestClient(create_app(service.repository.root))
    manifest = datasets.manifest(project)
    identifier = manifest.images[0].id
    url = f"/projects/{project}/dataset/images/{identifier}"
    document = client.get(url).json()
    payload = {"base_revision": document["revision"], "annotation": document["annotation"]}
    payload["annotation"]["reviewed"] = True
    assert client.put(url, json=payload).status_code == 200
    payload["annotation"]["reviewed"] = False
    assert client.put(url, json=payload).status_code == 409
    assert client.get(url).json()["annotation"]["reviewed"] is True


def test_fixture_manifest_paths_are_absolute_for_native_images(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Fixture path migration")
    service.demo(project.id)
    manifest = DatasetService(service).manifest(project.id)
    assert all(Path(item.image_path).is_absolute() and Path(item.image_path).is_file() for item in manifest.images)


def test_coco_labels_attach_to_preimported_normalized_image(tmp_path: Path) -> None:
    source = tmp_path / "originals"
    source.mkdir()
    image = source / "sample.jpg"
    Image.new("RGB", (100, 80), "blue").save(image)
    coco = {"images": [{"id": 1, "file_name": "sample.jpg", "width": 100, "height": 80}],
            "categories": [{"id": 1, "name": "part"}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 20, 30, 40]}]}
    filename = source / "labels.json"
    filename.write_text(json.dumps(coco))
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("COCO after images")
    service.import_media(project.id, [str(image)])
    original_path = service.get_project(project.id).media[0]
    datasets = DatasetService(service)
    manifest = datasets.import_coco(project.id, str(filename))
    assert len(manifest.images) == 1 and manifest.images[0].annotation_count == 1
    assert service.annotations(project.id).annotations[0].image_path == original_path
    # Source-name provenance also works when JSON arrives separately from images.
    second = service.create_project("COCO in another folder")
    service.import_media(second.id, [str(image)])
    elsewhere = tmp_path / "labels-only.json"
    elsewhere.write_text(json.dumps(coco))
    assert len(datasets.import_coco(second.id, str(elsewhere)).images) == 1


def test_snapshot_hash_matches_portable_dataset(tmp_path: Path) -> None:
    from engine.eval import dataset_hash
    from spec.models import EvalDataset
    service, datasets, project = real_dataset(tmp_path)
    version = datasets.create_version(project, "Portable identity")
    root = service.root(project) / "dataset-versions" / version.id
    portable = EvalDataset.model_validate_json((root / "annotations.json").read_text())
    assert version.dataset_hash == dataset_hash(portable, root)
    assert version.source_dataset_hash == dataset_hash(service.annotations(project), service.root(project))


def test_workflow_edit_rejects_stale_base(tmp_path: Path) -> None:
    from agent.templates import build_template
    service = WorkspaceService(tmp_path)
    project = service.create_project("Concurrent workflow", "pallets")
    service.demo(project.id)
    original = build_template("pallets", "media", "fixture-color-v1")[0]
    service.save_candidates(project.id, [original], "Count")
    edited = original.model_copy(deep=True)
    edited.blocks[1].params["min_conf"] = 0.3
    service.update_candidate(project.id, 0, edited, original)
    with pytest.raises(DatasetConflict, match="Workflow changed"):
        service.update_candidate(project.id, 0, original, original)
    assert service.candidate(project.id, 0) == edited


def test_coco_legacy_pixel_match_and_ambiguous_duplicates(tmp_path: Path) -> None:
    source = tmp_path / "sample.jpg"
    Image.new("RGB", (40, 30), "blue").save(source)
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Legacy media")
    service.import_media(project.id, [str(source)])
    (service.root(project.id) / "media/media-sources.json").unlink()
    coco = {"images": [{"id": 1, "file_name": "sample.jpg", "width": 40, "height": 30}],
            "categories": [], "annotations": []}
    filename = tmp_path / "labels.json"
    filename.write_text(json.dumps(coco))
    datasets = DatasetService(service)
    assert len(datasets.import_coco(project.id, str(filename)).images) == 1
    service.import_media(project.id, [str(source)])
    with pytest.raises(ValueError, match="multiple imported images"):
        datasets.import_coco(project.id, str(filename))
    assert len(service.get_project(project.id).media) == 2
