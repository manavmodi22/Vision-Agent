"""Meaningful invariants for graph compilation, execution and evidence gates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from engine.blocks.logic import parse_rule
from engine.blocks.reading import read_native
from engine.blocks.spatial import inside_polygon
from engine.compiler import CompileError, compile_pipeline
from engine.eval import dataset_hash, evaluate, spec_hash
from engine.eval.metrics import match_detections
from engine.models import ModelUnavailable
from engine.runtime import run_pipeline
from engine.runtime.fixtures import generate_demo
from spec.models import Detection, EvalDataset, PipelineSpec


def lane_spec() -> PipelineSpec:
    return PipelineSpec.model_validate({
        "name": "synthetic-lanes", "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [
            {"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
            {"id": "det", "type": "detect", "params": {"model": "fixture-color-v1", "classes": ["pallet"]},
             "in": {"image": "$sample.frame"}},
            {"id": "zones", "type": "zone_filter", "params": {"zones": "zones/lanes.json"},
             "in": {"dets": "$det.dets"}},
            {"id": "count", "type": "count_per_zone", "in": {"dets": "$zones.dets"}},
            {"id": "full", "type": "rule", "params": {"when": "count >= 3"}, "in": {"value": "$count.counts"}},
            {"id": "out", "type": "sink_event", "in": {"event": "$full.event"}},
        ], "eval": {"metric": "count_mae", "target": 0.5},
    })


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, EvalDataset, PipelineSpec]:
    return tmp_path, generate_demo(tmp_path), lane_spec()


def test_pipeline_preview_counts_boxes_and_events(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    result = run_pipeline(spec, root, max_frames=2)
    assert len(result.frames) == 2
    assert result.frames[0].counts == {"A": 0, "B": 2, "C": 0, "D": 2}
    assert result.frames[1].counts == {"A": 1, "B": 3, "C": 1, "D": 3}
    assert [e["zone"] for e in result.frames[1].events] == ["B", "D"]
    predicted = sorted(result.frames[1].detections, key=lambda d: (d.zone or "", d.box[1]))
    expected = sorted(dataset.annotations[1].detections, key=lambda d: (d.zone or "", d.box[1]))
    assert [d.box for d in predicted] == [d.box for d in expected]
    assert any("SYNTHETIC" in w for w in result.warnings)


def test_full_reviewed_eval_uses_same_detections(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    result = evaluate(spec, dataset, root)
    assert result.passed and result.count_mae == 0
    assert result.precision == result.recall == 1
    assert result.sample_count == 16 and result.failures == []
    assert result.spec_hash == spec_hash(spec, root)
    assert result.dataset_hash == dataset_hash(dataset, root)


def test_evaluation_catches_extra_and_missing_labels(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    dataset.annotations = dataset.annotations[:1]
    dataset.annotations[0].detections.pop()
    result = evaluate(spec, dataset, root)
    assert result.precision == 0.75 and result.recall == 1
    assert result.count_mae == 0.25
    assert result.failures[0]["false_positives"] == 1


def test_labels_and_pixels_and_zones_change_fingerprint(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    before = dataset_hash(dataset, root)
    dataset.annotations[0].detections.pop()
    assert before != dataset_hash(dataset, root)
    before = dataset_hash(dataset, root)
    Image.new("RGB", (640, 400)).save(dataset.annotations[0].image_path)
    assert before != dataset_hash(dataset, root)
    before_spec = spec_hash(spec, root)
    zones_file = root / "zones/lanes.json"
    zones_file.write_text(zones_file.read_text() + "\n")
    assert before_spec != spec_hash(spec, root)


def test_eval_empty_unreviewed_duplicate_and_vacuous_rejected(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    with pytest.raises(ValueError, match="nonempty"):
        evaluate(spec, EvalDataset(id="empty"), root)
    dataset.annotations[0].reviewed = False
    with pytest.raises(ValueError, match="reviewed"):
        evaluate(spec, dataset, root)
    dataset.annotations[0].reviewed = True
    dataset.annotations.append(dataset.annotations[0])
    with pytest.raises(ValueError, match="unique"):
        evaluate(spec, dataset, root)


@pytest.mark.parametrize("expression", ["__import__('os').system('id')", "count >= 1 or True", "count > float('nan')", "count.__class__", "count >= -1"])
def test_rule_language_rejects_code(expression: str) -> None:
    with pytest.raises(ValueError, match="Rule must"):
        parse_rule(expression)


def test_rule_language_comparisons() -> None:
    assert parse_rule("count >= 12").matches(12)
    assert not parse_rule("count > 12").matches(12)
    assert parse_rule(" count != 1.5 ").matches(2)


@pytest.mark.parametrize("change, message", [
    ("reference", "Unresolved"), ("port", "Port mismatch"), ("params", "Invalid parameters"),
    ("duplicate", "unique"), ("unsupported", "Unsupported block"), ("missing", "requires inputs"),
])
def test_compiler_rejects_invalid_graphs(project: tuple[Path, EvalDataset, PipelineSpec], change: str, message: str) -> None:
    root, _, spec = project
    if change == "reference":
        spec.blocks[1].inputs["image"] = "$missing.frame"
    elif change == "port":
        spec.blocks[1].inputs["image"] = "$inputs.source"
    elif change == "params":
        spec.blocks[1].params["made_up"] = True
    elif change == "duplicate":
        spec.blocks[1].id = "sample"
    elif change == "unsupported":
        spec.blocks[1].type = "segment"
    elif change == "missing":
        spec.blocks[1].inputs = {}
    with pytest.raises(CompileError, match=message):
        compile_pipeline(spec, root)


def test_cycle_is_detected(tmp_path: Path) -> None:
    spec = PipelineSpec.model_validate({"name": "cycle", "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "a", "type": "resize", "in": {"image": "$b.image"}},
                   {"id": "b", "type": "resize", "in": {"image": "$a.image"}}]})
    with pytest.raises(CompileError, match="Cycle"):
        compile_pipeline(spec, tmp_path)


def test_unknown_model_never_becomes_fixture(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, _, spec = project
    spec.blocks[1].params["model"] = "unknown"
    with pytest.raises(ModelUnavailable, match="Unknown"):
        compile_pipeline(spec, root)


def test_temporal_rules_can_be_authored_on_images_with_explicit_warning(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, _, spec = project
    spec.blocks[4].params["hold_s"] = 30
    compiled = compile_pipeline(spec, root)
    assert any("duration is not evaluated on independent images" in item for item in compiled.warnings)


def test_duplicate_boxes_cannot_match_one_truth_twice() -> None:
    box = Detection(label="pallet", confidence=0.9, box=[0, 0, 0.5, 0.5])
    result = match_detections([box, box], [box])
    assert result.true_positive == 1 and result.false_positive == 1
    wrong_class = box.model_copy(update={"label": "person"})
    assert match_detections([wrong_class], [box]).true_positive == 0


def test_polygon_boundary_and_concavity() -> None:
    polygon = [(0.0, 0.0), (1.0, 0.0), (1.0, 0.5), (0.5, 0.5), (0.5, 1.0), (0.0, 1.0)]
    assert inside_polygon(0, 0.5, polygon)
    assert inside_polygon(0.25, 0.75, polygon)
    assert not inside_polygon(0.75, 0.75, polygon)


def test_invalid_box_and_schema_version_rejected() -> None:
    with pytest.raises(ValidationError):
        Detection(label="pallet", confidence=1, box=[0, 0, 2, 1])
    with pytest.raises(ValidationError):
        PipelineSpec.model_validate({"spec_version": "99", "name": "bad", "inputs": {}, "blocks": []})


def test_native_bridge_failure_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISION_APP_BINARY", raising=False)
    with pytest.raises(ValueError, match="native app"):
        read_native(Image.new("RGB", (10, 10)))


def test_json_roundtrip(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    _, _, spec = project
    serialized = spec.model_dump_json(by_alias=True)
    assert '"in":' in serialized
    assert PipelineSpec.model_validate(json.loads(serialized)) == spec


def test_ground_truth_zones_are_derived_from_geometry(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    dataset.annotations = dataset.annotations[:1]
    for detection in dataset.annotations[0].detections:
        detection.zone = None
    score = evaluate(spec, dataset, root)
    assert score.count_mae == 0 and score.precision == 1


def test_crop_restores_original_box_coordinates(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    from spec.models import BlockSpec
    root, _, spec = project
    spec.blocks.insert(1, BlockSpec(id="roi", type="crop", params={"box": [0, 0, 0.5, 1]},
                                   inputs={"image": "$sample.frame"}))
    spec.blocks[2].inputs["image"] = "$roi.image"
    frame = run_pipeline(spec, root, max_frames=1).frames[0]
    assert frame.counts == {"A": 0, "B": 2, "C": 0, "D": 0}
    assert frame.detections[0].box == [195 / 640, 90 / 400, 285 / 640, 145 / 400]


def test_native_reading_match_and_barcode_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.adapters import legacy as executor
    from engine.blocks.reading import VisionReading
    Image.new("RGB", (100, 100)).save(tmp_path / "label.png")
    bridge = tmp_path / "bridge"
    bridge.write_bytes(b"synthetic-native-bridge-test")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    monkeypatch.setattr(executor, "read_native", lambda image: VisionReading(texts=["SKU-001"], barcodes=["12345"]))
    for kind, expected in (("ocr", "SKU-001"), ("barcode", "12345")):
        spec = PipelineSpec.model_validate({"name": "labels", "inputs": {"source": {"type": "image_file", "path": "label.png"}},
            "blocks": [{"id": "f", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                       {"id": "read", "type": kind, "in": {"image": "$f.frame"}},
                       {"id": "match", "type": "match", "params": {"expected": expected, "mode": "exact"}, "in": {"text": "$read.text"}},
                       {"id": "out", "type": "sink_event", "in": {"event": "$match.event"}}]})
        frame = run_pipeline(spec, tmp_path).frames[0]
        assert frame.texts == [expected] and frame.events[0]["matched"] is True


def test_video_sampling_and_temporal_rule(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    import cv2
    root, dataset, spec = project
    image = cv2.imread(dataset.annotations[1].image_path)
    path = root / "test.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 400))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(image)
    writer.release()
    spec.inputs["source"].type = "video_file"
    spec.inputs["source"].path = "test.mp4"
    spec.blocks[4].params["hold_s"] = 0.3
    spec.blocks[4].params["when"] = "count >= 1"
    result = run_pipeline(spec, root, max_frames=10)
    assert len(result.frames) == 2
    assert result.frames[0].timestamp_s == 0 and result.frames[1].timestamp_s == 0.5
    assert result.frames[0].events == [] and result.frames[1].events


def test_default_zone_parameter_is_also_fingerprinted(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, _, spec = project
    spec.blocks[2].params = {}
    before = spec_hash(spec, root)
    path = root / "zones/lanes.json"
    path.write_text(path.read_text() + "\n")
    assert before != spec_hash(spec, root)


def test_model_license_policy_has_explicit_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.models import manager
    monkeypatch.setattr(manager, "list_models", lambda: [{"id": "custom", "license": "unverified", "available": True}])
    with pytest.raises(ModelUnavailable, match="unapproved license"):
        manager.validate_model("custom")
    monkeypatch.setattr(manager, "list_models", lambda: [{"id": "custom", "license": "AGPL-3.0", "available": True}])
    with pytest.raises(ModelUnavailable, match="opt-in"):
        manager.validate_model("custom")
    manager.validate_model("custom", allow_agpl=True)


def test_ambiguous_multiple_detector_branches_are_rejected(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, _, spec = project
    duplicate = spec.blocks[1].model_copy(deep=True)
    duplicate.id = "other_detector"
    spec.blocks.append(duplicate)
    with pytest.raises(CompileError, match="one detector"):
        compile_pipeline(spec, root)


def test_resize_preserves_counts_and_normalized_geometry(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    from spec.models import BlockSpec
    root, dataset, spec = project
    spec.blocks.insert(1, BlockSpec(id="small", type="resize", params={"width": 320, "height": 200},
                                   inputs={"image": "$sample.frame"}))
    spec.blocks[2].inputs["image"] = "$small.image"
    frame = run_pipeline(spec, root, max_frames=1).frames[0]
    assert frame.counts == {"A": 0, "B": 2, "C": 0, "D": 2}
    for predicted, truth in zip(frame.detections, dataset.annotations[0].detections, strict=True):
        assert predicted.box == pytest.approx(truth.box, abs=0.01)


def test_many_independent_photos_never_synthesize_dwell_time(project: tuple[Path, EvalDataset, PipelineSpec]) -> None:
    root, dataset, spec = project
    spec.blocks[4].params["hold_s"] = 30
    content = Path(dataset.annotations[1].image_path).read_bytes()
    for index in range(40):
        (root / "media" / f"repeat-{index:03d}.png").write_bytes(content)
    result = run_pipeline(spec, root, max_frames=100)
    assert len(result.frames) == 56
    assert all(frame.timestamp_s == 0 and not frame.events for frame in result.frames)
    assert any("duration is not evaluated" in item for item in result.warnings)
    evaluation = evaluate(spec, dataset, root)
    assert evaluation.passed and any("duration is not evaluated" in item for item in evaluation.warnings)


def test_independent_image_execution_resets_state_even_if_a_source_supplies_times(
    project: tuple[Path, EvalDataset, PipelineSpec], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.runtime as runtime
    root, dataset, spec = project
    spec.blocks[4].params["hold_s"] = .5
    path = Path(dataset.annotations[1].image_path)
    monkeypatch.setattr(runtime, "source_frames", lambda *args: [(path, 0), (path, 60)])
    result = runtime.run_pipeline(spec, root)
    assert all(not frame.events for frame in result.frames)
