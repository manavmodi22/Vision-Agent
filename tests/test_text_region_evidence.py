"""Software-only annotation/exposure contracts, never real OCR quality evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from engine.datasets import DatasetService
from engine.eval import evaluate
from engine.eval.configuration import read_configuration, save_configuration
from engine.eval.hashes import dataset_hash
from engine.eval.protocol import acceptance_blockers, freeze_protocol, protocol_dataset
from engine.eval.usage import preserve_annotation_usage, read_usage
from engine.models.artifacts import content_hash
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment, EvidencePolicy
from spec.inference import TextObservation
from spec.models import Annotation, EvalDataset, FrameResult, PipelineSpec
from spec.text_annotations import TextRegion, TextRegionSeed


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[WorkspaceService, str]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for index in range(3):
        Image.new("RGB", (80, 60), (20 + index * 50, 100, 200)).save(inputs / f"image-{index}.png")
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Software-only text-region evidence tests")
    service.import_media(project.id, [str(inputs)])
    return service, project.id


def reserve_last(service: WorkspaceService, identifier: str) -> None:
    root = service.root(identifier)
    dataset = service.annotations(identifier)
    configuration = read_configuration(root, dataset)
    save_configuration(root, dataset, EvaluationConfigurationUpdate(
        expected_revision=configuration.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, scene_group="heldout" if index == 2 else "development",
            split="acceptance" if index == 2 else "validation", data_origin="real")
            for index, row in enumerate(configuration.images)],
        policy=EvidencePolicy(intended_use="Software test only, generated colors are not real OCR evidence",
            independent_group_basis="Distinct test source files", coverage_rationale="This software scaffold only",
            required_acceptance_groups=["heldout"])))


def reasons(service: WorkspaceService, identifier: str, path: str) -> list[str]:
    root = service.root(identifier)
    return next(row.exposure_reasons for row in read_configuration(root, service.annotations(identifier)).images
                if (root / row.image_path).resolve() == Path(path).resolve())


def region(path: str, *, seeded: bool = False, transcript: str | None = "ABC-990") -> TextRegion:
    seed = TextRegionSeed(model_id="apple-vision", adapter_id="apple-vision", identity_hash="a" * 64,
        block_id="read", observation_index=0, observation=TextObservation(text="ABC-990", kind="ocr"),
        input_to_frame=(0, 0, 1, 1), image_sha256=content_hash(Path(path)),
        created_at="2026-10-28T10:00:00Z") if seeded else None
    return TextRegion(id="region-1", polygon=[(.1, .2), (.8, .2), (.8, .6), (.1, .6)],
                      transcript=transcript, seed=seed)


def with_regions(data: EvalDataset, regions: list[TextRegion], index: int = -1) -> EvalDataset:
    incoming = data.model_copy(deep=True)
    value = incoming.annotations[index].model_dump(mode="json")
    value.update(text_regions=[item.model_dump(mode="json") for item in regions], expected_text_source="regions")
    incoming.annotations[index] = Annotation.model_validate(value)
    return incoming


def reader() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Software-only reader",
        "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "f", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "read", "type": "ocr", "in": {"image": "$f.frame"}}],
        "eval": {"metric": "text_accuracy", "target": 1}})


def mock_reader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, texts: list[str]) -> None:
    bridge = tmp_path / "mock-reading-bridge"
    bridge.write_bytes(b"software test only, not a native executable")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    monkeypatch.setattr("engine.eval.execute_frame", lambda compiled, path, timestamp, state:
        FrameResult(image_path=str(path), texts=texts))


def test_imported_history_marks_pixels_without_creating_a_seed(workspace: tuple[WorkspaceService, str]) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    original = data.model_dump_json()
    preserve_annotation_usage(root, data, data, imported_exposures={path: ["Prior model-generated text-region seed"]})
    assert reasons(service, identifier, path) == ["Prior model-generated text-region seed"]
    assert service.annotations(identifier).model_dump_json() == original
    first = read_usage(root).model_dump_json()
    preserve_annotation_usage(root, data, data, imported_exposures={path: ["Prior model-generated text-region seed"]})
    assert read_usage(root).model_dump_json() == first


@pytest.mark.parametrize("kind", ["outside", "unknown", "duplicate_alias", "blank", "too_many"])
def test_rejected_imported_history_does_not_partially_persist(workspace: tuple[WorkspaceService, str], kind: str) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    path = data.annotations[0].image_path
    imported = {path: ["Known model use"]}
    if kind == "outside":
        imported[str(root.parent / "outside.png")] = ["Bad reference"]
    elif kind == "unknown":
        imported["media/unknown.png"] = ["Bad reference"]
    elif kind == "duplicate_alias":
        imported[Path(path).relative_to(root).as_posix()] = ["Duplicate reference"]
    elif kind == "blank":
        imported[data.annotations[1].image_path] = [" "]
    else:
        imported[data.annotations[1].image_path] = [f"Reason {index}" for index in range(1001)]
    original = (root / "annotations.json").read_bytes()
    before = read_usage(root).model_dump_json()
    with pytest.raises(ValueError):
        preserve_annotation_usage(root, data, data, imported_exposures=imported)
    assert (root / "annotations.json").read_bytes() == original
    assert read_usage(root).model_dump_json() == before


def test_missing_pixels_do_not_persist_earlier_imported_history(workspace: tuple[WorkspaceService, str]) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    previous = service.annotations(identifier)
    incoming = previous.model_copy(deep=True)
    incoming.annotations.append(Annotation(image_path="media/missing.png"))
    before = read_usage(root).model_dump_json()
    with pytest.raises((ValueError, FileNotFoundError)):
        preserve_annotation_usage(root, previous, incoming,
            imported_exposures={previous.annotations[0].image_path: ["Prior model use"]})
    assert read_usage(root).model_dump_json() == before


def test_imported_exposure_survives_renaming_and_reencoding(workspace: tuple[WorkspaceService, str], tmp_path: Path) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    original = data.annotations[0].image_path
    preserve_annotation_usage(root, data, data, imported_exposures={original: ["Prior model-generated text-region seed"]})
    renamed = tmp_path / "renamed.bmp"
    with Image.open(original) as image:
        image.save(renamed)
    service.import_media(identifier, [str(renamed)])
    added = service.annotations(identifier).annotations[-1].image_path
    assert added != original
    assert reasons(service, identifier, added) == ["Prior model-generated text-region seed"]


def test_manual_regions_and_review_leave_reserved_acceptance_untouched(
        workspace: tuple[WorkspaceService, str], monkeypatch: pytest.MonkeyPatch) -> None:
    service, identifier = workspace
    reserve_last(service, identifier)
    root = service.root(identifier)
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    before = read_usage(root).model_dump_json()
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Manual annotation must not execute any model")
    monkeypatch.setattr("engine.adapters.registry.execute_legacy", forbidden)
    def forbidden_scan(*args: object, **kwargs: object) -> None:
        pytest.fail("Unseeded manual autosave must not scan or hash image pixels")
    data = with_regions(data, [region(path, transcript=None)])
    with monkeypatch.context() as save_patch:
        save_patch.setattr("engine.eval.usage.ExposureSnapshot", forbidden_scan)
        save_patch.setattr("engine.eval.usage.evidence_lock", forbidden_scan)
        service.save_annotations(identifier, data)
        data = with_regions(service.annotations(identifier), [region(path)])
        service.save_annotations(identifier, data)
        data = service.annotations(identifier)
        data.annotations[-1].reviewed = True
        service.save_annotations(identifier, data)
    assert service.annotations(identifier).annotations[-1].reviewed
    assert reasons(service, identifier, path) == []
    assert read_usage(root).model_dump_json() == before


@pytest.mark.parametrize("edit", ["transcript", "remove_seed", "delete_region"])
def test_seed_exposure_survives_edit_or_deletion(
        workspace: tuple[WorkspaceService, str], edit: str) -> None:
    service, identifier = workspace
    reserve_last(service, identifier)
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    service.save_annotations(identifier, with_regions(data, [region(path, seeded=True)]))
    data = service.annotations(identifier)
    updated = data.annotations[-1].text_regions[0].model_copy(deep=True)
    if edit == "transcript":
        updated.transcript = "Human corrected X / Х"
    elif edit == "remove_seed":
        updated.seed = None
    incoming = with_regions(data, [] if edit == "delete_region" else [updated])
    if edit == "remove_seed":
        before = service.annotations(identifier).model_dump_json()
        with pytest.raises(ValueError, match="provenance cannot be changed or removed"):
            service.save_annotations(identifier, incoming)
        assert service.annotations(identifier).model_dump_json() == before
    else:
        service.save_annotations(identifier, incoming)
    assert "Prior model-generated text-region seed" in reasons(service, identifier, path)
    blockers = acceptance_blockers(service.root(identifier), service.annotations(identifier), [reader()], 0)
    assert any("already been used" in reason for reason in blockers)


def test_legacy_seed_without_ledger_is_detected_and_deletion_cannot_erase_it(
        workspace: tuple[WorkspaceService, str]) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    legacy = with_regions(data, [region(path, seeded=True)])
    atomic_model(root / "annotations.json", legacy)
    assert not (root / "evaluation/usage.json").exists()
    assert reasons(service, identifier, path) == ["Prior model-generated text-region seed"]
    service.save_annotations(identifier, with_regions(legacy, []))
    assert read_usage(root).uses
    assert reasons(service, identifier, path) == ["Prior model-generated text-region seed"]


@pytest.mark.parametrize("changed", ["polygon", "transcript", "policy", "seed"])
def test_region_fields_bind_dataset_and_frozen_protocol(
        workspace: tuple[WorkspaceService, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    data = with_regions(data, [region(path)])
    for annotation in data.annotations:
        annotation.reviewed = True
    service.save_annotations(identifier, data)
    mock_reader(tmp_path, monkeypatch, ["ABC-990"])
    frozen = freeze_protocol(root, data, [reader()], [0])
    original_hash = dataset_hash(data, root)
    changed_data = data.model_copy(deep=True)
    row = changed_data.annotations[-1]
    if changed == "polygon":
        row.text_regions[0].polygon = [(.2, .2), (.8, .2), (.8, .6), (.2, .6)]
        row.text_regions[0].box = None
    elif changed == "transcript":
        row.text_regions[0].transcript = "ХABC-990"
    elif changed == "policy":
        row.expected_text_source = "manual"
    else:
        row.text_regions[0].seed = region(path, seeded=True).seed
    changed_data = EvalDataset.model_validate(changed_data.model_dump(mode="json"))
    assert dataset_hash(changed_data, root) != original_hash
    with pytest.raises(ValueError, match="labels|pixels|dataset"):
        protocol_dataset(root, changed_data, frozen)


def test_region_metric_preserves_duplicate_literals_but_does_not_score_geometry(
        workspace: tuple[WorkspaceService, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    literals = ["X", "Х", "e\u0301", "é", "X"]
    for index, annotation in enumerate(data.annotations):
        rows = [region(annotation.image_path, transcript=value).model_copy(update={"id": f"region-{i}"})
                for i, value in enumerate(literals)]
        data = with_regions(data, rows, index)
        data.annotations[index].reviewed = True
    service.save_annotations(identifier, data)
    saved = service.annotations(identifier)
    assert not any(row.reviewed for row in saved.annotations)
    for row in saved.annotations:
        row.reviewed = True
    service.save_annotations(identifier, saved)
    saved = service.annotations(identifier)
    assert saved.annotations[0].expected_texts == literals
    mock_reader(tmp_path, monkeypatch, literals[::-1])
    score = evaluate(reader(), saved, root)
    assert score.text_accuracy == 1 and score.character_error_rate == 0
    assert any("localization, polygon IoU, reading order or duplicate-instance geometry" in item for item in score.warnings)
    assert not score.promotion_eligible
    mock_reader(tmp_path, monkeypatch, literals[:-1])
    fewer = evaluate(reader(), saved, root)
    assert fewer.text_accuracy == 0 and fewer.character_error_rate is not None and fewer.character_error_rate > 0


def test_snapshot_roundtrip_keeps_original_seed_and_literals(
        workspace: tuple[WorkspaceService, str]) -> None:
    service, identifier = workspace
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    service.save_annotations(identifier, with_regions(data, [region(path, seeded=True, transcript="ХABC-990")]))
    version = DatasetService(service).create_version(identifier, "Text region snapshot")
    root = service.root(identifier) / "dataset-versions" / version.id
    saved = EvalDataset.model_validate_json((root / "annotations.json").read_text())
    assert saved.annotations[-1].text_regions == service.annotations(identifier).annotations[-1].text_regions
    assert saved.annotations[-1].expected_texts == ["ХABC-990"]
    assert dataset_hash(saved, root) == version.dataset_hash


def test_coco_overwrite_cannot_clear_historical_seed_exposure(
        workspace: tuple[WorkspaceService, str], tmp_path: Path) -> None:
    service, identifier = workspace
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    service.save_annotations(identifier, with_regions(data, [region(path, seeded=True)]))
    datasets = DatasetService(service)
    source = tmp_path / "replace.json"
    source.write_text(json.dumps(datasets.export_coco(identifier)))
    datasets.import_coco(identifier, str(source), replace_existing=True)
    assert "Prior model-generated text-region seed" in reasons(service, identifier, path)


@pytest.mark.parametrize("invalid", ["geometry", "duplicate_image", "empty_reviewed_transcript"])
def test_invalid_incoming_labels_do_not_record_a_valid_seed_first(
        workspace: tuple[WorkspaceService, str], invalid: str) -> None:
    service, identifier = workspace
    root = service.root(identifier)
    data = service.annotations(identifier)
    data = with_regions(data, [region(data.annotations[-1].image_path, seeded=True)])
    if invalid == "geometry":
        data.annotations[-1].text_regions[0].polygon[0] = (-1, .2)
    elif invalid == "duplicate_image":
        data.annotations[0].image_path = data.annotations[-1].image_path
    else:
        data.annotations[-1].reviewed = True
        data.annotations[-1].text_regions[0].transcript = None
    original = (root / "annotations.json").read_bytes()
    before = read_usage(root).model_dump_json()
    with pytest.raises(ValueError):
        service.save_annotations(identifier, data)
    assert (root / "annotations.json").read_bytes() == original
    assert read_usage(root).model_dump_json() == before


def test_deleted_seed_history_survives_portable_archive_into_a_new_project(
        workspace: tuple[WorkspaceService, str], tmp_path: Path) -> None:
    from engine.dataset_archive import LabelArchiveService
    service, identifier = workspace
    data = service.annotations(identifier)
    image_path = data.annotations[-1].image_path
    service.save_annotations(identifier, with_regions(data, [region(image_path, seeded=True)]))
    service.save_annotations(identifier, with_regions(service.annotations(identifier), []))
    archive = LabelArchiveService(service).export_labels(identifier)
    assert archive.images[-1].annotation.text_regions == []
    assert archive.images[-1].model_exposure_reasons == ["Prior model-generated text-region seed"]
    source = tmp_path / "deleted-seed.vision-labels.json"
    source.write_text(archive.model_dump_json())
    destination = service.create_project("Software-only archive destination")
    service.import_media(destination.id, [row.image_path for row in service.annotations(identifier).annotations])
    revision = DatasetService(service).manifest(destination.id).revision
    LabelArchiveService(service).import_labels(destination.id, str(source), revision)
    imported = service.annotations(destination.id)
    assert imported.annotations[-1].text_regions == []
    assert reasons(service, destination.id, imported.annotations[-1].image_path) == ["Prior model-generated text-region seed"]


def test_snapshot_portable_labels_preserve_exposure_after_seed_deletion(
        workspace: tuple[WorkspaceService, str]) -> None:
    from engine.dataset_archive import LabelArchiveService
    service, identifier = workspace
    data = service.annotations(identifier)
    path = data.annotations[-1].image_path
    service.save_annotations(identifier, with_regions(data, [region(path, seeded=True)]))
    service.save_annotations(identifier, with_regions(service.annotations(identifier), []))
    version = DatasetService(service).create_version(identifier, "After deleting copied prediction")
    folder = service.root(identifier) / "dataset-versions" / version.id
    source = folder / "labels.vision-labels.json"
    destination = service.create_project("Software-only snapshot destination")
    service.import_media(destination.id, [str(folder / "images")])
    manifest = DatasetService(service).manifest(destination.id)
    LabelArchiveService(service).import_labels(destination.id, str(source), manifest.revision)
    rows = service.annotations(destination.id)
    assert all(not row.text_regions for row in rows.annotations)
    assert any("Prior model-generated text-region seed" in reasons(service, destination.id, row.image_path)
               for row in rows.annotations)
