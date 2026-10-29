"""Software-only evidence gates; generated fixtures are not real quality claims."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from engine.adapters import legacy
from engine.blocks.reading import VisionReading
from engine.eval import evaluate
from engine.eval.protocol import (
    acceptance_blockers,
    freeze_protocol,
    mark_usage,
    read_configuration,
    save_configuration,
    validate_evidence,
)
from engine.media import import_paths
from engine.store.repository import atomic_model
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment, EvidencePolicy
from spec.models import Annotation, EvalDataset, PipelineSpec


def reader(kind: str = "ocr") -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Software-only reader test",
        "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "f", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "read", "type": kind, "in": {"image": "$f.frame"}}],
        "eval": {"metric": "text_accuracy", "target": 1}})


@pytest.fixture
def scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, EvalDataset]:
    root, inputs = tmp_path / "project", tmp_path / "inputs"
    inputs.mkdir()
    files = []
    for index in range(4):
        path = inputs / f"image-{index}.png"
        Image.new("RGB", (30, 20), (index * 40, 100, 200)).save(path)
        files.append(str(path))
    paths = import_paths(files, root / "media")
    data = EvalDataset(id="software-scaffold", annotations=[Annotation(
        image_path=path, reviewed=True, expected_texts=["ABC"]) for path in paths])
    atomic_model(root / "annotations.json", data)
    bridge = tmp_path / "bridge"
    bridge.write_bytes(b"mocked-native-software-test")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    monkeypatch.setattr(legacy, "read_native", lambda image: VisionReading(texts=["ABC"], barcodes=["ABC"]))
    return root, data


def configure(root: Path, data: EvalDataset) -> None:
    current = read_configuration(root, data)
    save_configuration(root, data, EvaluationConfigurationUpdate(expected_revision=current.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, scene_group="accept" if i == 3 else "dev",
            split="acceptance" if i == 3 else "validation", data_origin="real") for i, row in enumerate(current.images)],
        policy=EvidencePolicy(intended_use="Software test only", independent_group_basis="Test-declared separate inputs",
            coverage_rationale="One deliberately declared held-out scene; no broad quality claim", required_acceptance_groups=["accept"])))


def test_one_selected_acceptance_can_qualify_without_mutating_human_labels(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    before = data.model_dump_json()
    configure(root, data)
    assert acceptance_blockers(root, data, [reader()], 0) == []
    protocol = freeze_protocol(root, data, [reader()], [0], "acceptance")
    score = evaluate(reader(), data, root, protocol=protocol)
    assert score.passed and score.promotion_eligible and score.evidence_scope == "acceptance"
    assert score.sample_count == 1  # Adequacy is an explicit narrow policy, never a magic image count.
    assert data.model_dump_json() == before
    assert EvalDataset.model_validate_json((root / "annotations.json").read_text()).model_dump_json() == before
    validate_evidence(root, data, [reader()], score)
    assert freeze_protocol(root, data, [reader()], [0], "acceptance") == protocol
    with pytest.raises(ValueError, match="already consumed"):
        evaluate(reader(), data, root, protocol=protocol)
    tuned = reader().model_copy(update={"name": "Tuned after acceptance"})
    with pytest.raises(ValueError, match="already been used"):
        freeze_protocol(root, data, [tuned], [0], "acceptance")


def test_validation_shares_protocol_but_never_promotes(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    first, second = reader(), reader().model_copy(update={"name": "Alternative"})
    protocol = freeze_protocol(root, data, [first, second], [0, 1])
    results = [evaluate(spec, data, root, protocol=protocol) for spec in (first, second)]
    assert all(score.passed and not score.promotion_eligible and score.evidence_scope == "sample" for score in results)
    assert len({score.protocol_hash for score in results}) == 1
    assert len({score.dataset_hash for score in results}) == 1
    with pytest.raises(ValueError, match="one already-selected"):
        freeze_protocol(root, data, [first, second], [0, 1], "acceptance")
    with pytest.raises(ValueError, match="output task"):
        freeze_protocol(root, data, [reader("ocr"), reader("barcode")], [0, 1])


def test_model_exposure_invalidates_freshness_but_not_configuration_revision(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    configure(root, data)
    before = read_configuration(root, data)
    mark_usage(root, [data.annotations[-1].image_path], "preview")
    after = read_configuration(root, data)
    assert before.revision == after.revision
    assert after.images[-1].exposure_reasons
    with pytest.raises(ValueError, match="already been used"):
        freeze_protocol(root, data, [reader()], [0], "acceptance")


def test_failed_acceptance_is_consumed_before_inference(scaffold: tuple[Path, EvalDataset], monkeypatch: pytest.MonkeyPatch) -> None:
    root, data = scaffold
    configure(root, data)
    protocol = freeze_protocol(root, data, [reader()], [0], "acceptance")
    def fail(image: Image.Image) -> VisionReading:
        raise ValueError("software-test inference failure")
    monkeypatch.setattr(legacy, "read_native", fail)
    with pytest.raises(ValueError, match="inference failure"):
        evaluate(reader(), data, root, protocol=protocol)
    with pytest.raises(ValueError, match="already consumed"):
        evaluate(reader(), data, root, protocol=protocol)


def test_group_changes_stale_saved_evidence_and_cas(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    current = read_configuration(root, data)
    protocol = freeze_protocol(root, data, [reader()], [0])
    score = evaluate(reader(), data, root, protocol=protocol)
    configure(root, data)
    with pytest.raises(ValueError, match="assignments or policy"):
        validate_evidence(root, data, [reader()], score)
    with pytest.raises(ValueError, match="reload"):
        save_configuration(root, data, EvaluationConfigurationUpdate(expected_revision=current.revision,
            assignments=[], policy=EvidencePolicy()))


def test_same_clip_cannot_be_made_independent_by_different_scene_names(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    sources = root / "media/media-sources.json"
    records = json.loads(sources.read_text())
    for row in records.values():
        row["source_sha256"] = "f" * 64
        row["source_kind"] = "recorded_video"
    sources.write_text(json.dumps(records))
    configure(root, data)
    assert any("source asset" in reason or "overlaps" in reason for reason in acceptance_blockers(root, data, [reader()], 0))


def test_recipe_baseline_exists_before_first_evaluation() -> None:
    code = '''from pathlib import Path
import engine.eval as evaluator
from engine.eval import recipe
assert isinstance(recipe._LOADED_RECIPE, str)
recipe._current_recipe=lambda: 'edited-after-import'
try:
    evaluator.evaluate(None, None, Path('.'))
except ValueError as error:
    assert 'restart' in str(error)
else:
    raise AssertionError('old loaded recipe mislabeled with new bytes')
'''
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_upgrade_preserves_exposure_but_fresh_import_remains_usable(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    source_file = root / "media/media-sources.json"
    records = json.loads(source_file.read_text())
    old = Path(data.annotations[-1].image_path)
    records[old.name].pop("exposure_tracking_version")
    source_file.write_text(json.dumps(records))
    (root / "build.json").write_text(json.dumps({"view": {"preview": {"frames": [{"image_path": str(old)}]}}}))
    assert not (root / "evaluation/usage.json").exists()
    rows = read_configuration(root, data).images
    assert any("Legacy" in reason for reason in rows[-1].exposure_reasons)
    assert "Prior saved model preview" in rows[-1].exposure_reasons
    configure(root, data)
    assert any("already been used" in reason for reason in acceptance_blockers(root, data, [reader()], 0))
    new_source = root.parent / "new-software-fixture.png"
    Image.new("RGB", (30, 20), (245, 210, 13)).save(new_source)
    imported = import_paths([str(new_source)], root / "media")[0]
    data.annotations.append(Annotation(image_path=imported, reviewed=True, expected_texts=["ABC"]))
    atomic_model(root / "annotations.json", data)
    current = read_configuration(root, data)
    save_configuration(root, data, EvaluationConfigurationUpdate(expected_revision=current.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, scene_group="fresh" if i == 4 else "dev",
            split="acceptance" if i == 4 else "validation", data_origin="real") for i, row in enumerate(current.images)],
        policy=EvidencePolicy(intended_use="Software test", independent_group_basis="Declared new source",
            coverage_rationale="Only this new scene", required_acceptance_groups=["fresh"])))
    assert acceptance_blockers(root, data, [reader()], 0) == []


def test_reencoded_duplicates_cannot_inflate_evaluation(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    copy = root / "same-pixels.bmp"
    with Image.open(data.annotations[0].image_path) as image:
        image.save(copy)
    data.annotations[1].image_path = str(copy)
    with pytest.raises(ValueError, match="duplicate inflation"):
        freeze_protocol(root, data, [reader()], [0])


def test_exposure_scan_hashes_each_image_once(scaffold: tuple[Path, EvalDataset], monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.eval.usage as usage
    from engine.evidence_metadata import image_identity
    root, data = scaffold
    records_file = root / "media/media-sources.json"
    records = json.loads(records_file.read_text())
    for record in records.values():
        record["source_sha256"] = "a" * 64
    records_file.write_text(json.dumps(records))
    mark_usage(root, [data.annotations[0].image_path], "preview")
    original = image_identity
    calls: list[str] = []
    def counted(project: Path, path: str) -> dict[str, str]:
        calls.append(path)
        return original(project, path)
    monkeypatch.setattr(usage, "image_identity", counted)
    current = read_configuration(root, data)
    assert len(calls) == len(data.annotations)
    assert all(row.exposure_reasons for row in current.images)


def test_known_synthetic_origin_cannot_be_changed_by_assignment(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    records_file = root / "media/media-sources.json"
    records = json.loads(records_file.read_text())
    records[Path(data.annotations[-1].image_path).name]["data_origin"] = "synthetic"
    records_file.write_text(json.dumps(records))
    with pytest.raises(ValueError, match="Known synthetic"):
        configure(root, data)


def test_training_rejects_same_source_groups_before_model_loading(scaffold: tuple[Path, EvalDataset]) -> None:
    from engine.train.validation import validate_training_data
    from spec.models import Detection
    root, data = scaffold
    records_file = root / "media/media-sources.json"
    records = json.loads(records_file.read_text())
    for record in records.values():
        record["source_sha256"] = "b" * 64
    records_file.write_text(json.dumps(records))
    for row in data.annotations:
        row.detections = [Detection(label="person", confidence=1, box=[.1, .1, .5, .8])]
    training = EvalDataset(id="train", annotations=data.annotations[:2])
    heldout = EvalDataset(id="validation", annotations=data.annotations[2:])
    with pytest.raises(ValueError, match="source asset crosses"):
        validate_training_data(training, heldout, root)


def test_unknown_run_paths_retain_original_source_exposure(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    new_media = root / "runs/test/media"
    new_media.mkdir(parents=True)
    frame = new_media / "frame.png"
    Image.new("RGB", (40, 20), (123, 50, 200)).save(frame)
    original = json.loads((root / "media/media-sources.json").read_text())[Path(data.annotations[-1].image_path).name]
    (new_media / "media-sources.json").write_text(json.dumps({frame.name: original}))
    mark_usage(root, [str(frame)], "uploaded video run")
    assert any("uploaded video run" in reason for reason in read_configuration(root, data).images[-1].exposure_reasons)


def test_live_pixels_are_exposed_without_frame_persistence(scaffold: tuple[Path, EvalDataset]) -> None:
    from engine.eval.protocol import mark_pixel_usage
    root, data = scaffold
    before = sorted(path.name for path in (root / "media").iterdir())
    with Image.open(data.annotations[-1].image_path) as image:
        mark_pixel_usage(root, image, "live_preview")
    assert before == sorted(path.name for path in (root / "media").iterdir())
    assert not (root / "runs").exists()
    assert any("live_preview" in reason for reason in read_configuration(root, data).images[-1].exposure_reasons)


def test_video_import_records_original_asset_frame_and_time(tmp_path: Path) -> None:
    import cv2
    import numpy as np

    from engine.evidence_metadata import source_record
    video = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter.fourcc(*"MJPG"), 2, (64, 48))
    assert writer.isOpened()
    for index in range(12):
        writer.write(np.full((48, 64, 3), index * 15, dtype=np.uint8))
    writer.release()
    root = tmp_path / "project"
    paths = import_paths([str(video)], root / "media", 3)
    records = [source_record(root, path) for path in paths]
    assert len({record["source_sha256"] for record in records}) == 1
    assert [int(record["frame_index"]) for record in records] == [0, 4, 8]
    assert [float(record["timestamp_s"]) for record in records] == [0, 2, 4]
    assert all(record["exposure_tracking_version"] == "1" for record in records)


def test_one_asset_cannot_satisfy_two_independent_acceptance_groups(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    records_file = root / "media/media-sources.json"
    records = json.loads(records_file.read_text())
    for row in data.annotations[2:]:
        records[Path(row.image_path).name]["source_sha256"] = "d" * 64
    records_file.write_text(json.dumps(records))
    current = read_configuration(root, data)
    save_configuration(root, data, EvaluationConfigurationUpdate(expected_revision=current.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path,
            scene_group=("first" if i == 2 else "second") if i >= 2 else "dev",
            split="acceptance" if i >= 2 else "validation", data_origin="real") for i, row in enumerate(current.images)],
        policy=EvidencePolicy(intended_use="Software test", independent_group_basis="Two claimed groups",
            coverage_rationale="Test declaration", required_acceptance_groups=["first", "second"])))
    assert any("multiple independent" in reason for reason in acceptance_blockers(root, data, [reader()], 0))


def test_wrong_output_metric_cannot_qualify_vacuously(scaffold: tuple[Path, EvalDataset]) -> None:
    root, data = scaffold
    configure(root, data)
    spec = reader()
    spec.eval.metric = "count_mae"
    assert any("text_accuracy" in reason for reason in acceptance_blockers(root, data, [spec], 0))
