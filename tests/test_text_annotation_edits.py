"""Authoring boundaries prevent older clients and box imports losing text labels."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from engine.api import create_app
from engine.dataset_archive import LabelArchiveService
from engine.datasets import DatasetService, DatasetVersion
from engine.service import WorkspaceService
from spec.models import Annotation, EvalDataset
from spec.text_annotations import TextRegion


def setup(tmp_path: Path) -> tuple[WorkspaceService, DatasetService, str]:
    source = tmp_path / "image.png"
    Image.new("RGB", (100, 80), "blue").save(source)
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Text-region edit software test")
    service.import_media(project.id, [str(source)])
    dataset = service.annotations(project.id)
    dataset.annotations[0].text_regions = [TextRegion(id="text", transcript="ABC", polygon=[(.1, .2), (.8, .2), (.8, .5), (.1, .5)])]
    dataset.annotations[0].expected_text_source = "regions"
    service.save_annotations(project.id, dataset)
    return service, DatasetService(service), project.id


@pytest.mark.parametrize("route", ["image", "bulk"])
def test_old_client_omission_cannot_erase_regions(tmp_path: Path, route: str) -> None:
    service, datasets, project = setup(tmp_path)
    client = TestClient(create_app(service.repository.root))
    manifest = datasets.manifest(project)
    row = service.annotations(project).annotations[0].model_dump(mode="json")
    del row["text_regions"]
    del row["expected_text_source"]
    before = (service.root(project) / "annotations.json").read_bytes()
    if route == "image":
        response = client.put(f"/projects/{project}/dataset/images/{manifest.images[0].id}",
            json={"base_revision": manifest.revision, "annotation": row})
        assert response.status_code == 400 and "Update the editor" in response.text
    else:
        with pytest.raises(ValueError, match="Update the editor"):
            service.save_annotations(project, EvalDataset(id="legacy", annotations=[Annotation.model_validate(row)]))
    assert (service.root(project) / "annotations.json").read_bytes() == before


def test_region_edit_clears_review_and_requires_separate_review_save(tmp_path: Path) -> None:
    service, datasets, project = setup(tmp_path)
    manifest = datasets.manifest(project)
    opened = datasets.image(project, manifest.images[0].id)
    opened.annotation.reviewed = True
    reviewed = datasets.save_image(project, manifest.images[0].id, opened.revision, opened.annotation)
    assert reviewed.annotation.reviewed
    reviewed.annotation.text_regions[0].transcript = "NEW"
    edited = datasets.save_image(project, manifest.images[0].id, reviewed.revision, reviewed.annotation)
    assert not edited.annotation.reviewed and edited.annotation.expected_texts == ["NEW"]


def test_coco_only_replaces_boxes_not_transcripts_or_regions(tmp_path: Path) -> None:
    service, datasets, project = setup(tmp_path)
    before = service.annotations(project).annotations[0]
    coco = datasets.export_coco(project)
    path = tmp_path / "boxes.json"
    path.write_text(json.dumps(coco))
    datasets.import_coco(project, str(path), replace_existing=True)
    after = service.annotations(project).annotations[0]
    assert after.text_regions == before.text_regions and after.expected_text_source == "regions"
    assert after.expected_texts == ["ABC"] and not after.reviewed


def test_snapshot_v2_and_legacy_export_read_compatibility(tmp_path: Path) -> None:
    service, datasets, project = setup(tmp_path)
    version = datasets.create_version(project, "Text shapes")
    assert version.format_version == "2" and version.text_region_count == 1
    historical = version.model_dump(mode="json")
    del historical["format_version"]
    del historical["text_region_count"]
    assert DatasetVersion.model_validate(historical).format_version == "1"
    filename = service.root(project) / "annotations.json"
    old = json.loads(filename.read_text())
    for row in old["annotations"]:
        del row["text_regions"]
        del row["expected_text_source"]
    filename.write_text(json.dumps(old))
    before = filename.read_bytes()
    archive = LabelArchiveService(service).export_labels(project)
    assert archive.images[0].annotation.text_regions == []
    assert archive.images[0].annotation.expected_text_source == "manual"
    assert filename.read_bytes() == before
