"""Common envelopes preserve actual graph output and fail closed on stale evidence."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PIL import Image

import engine.adapters.legacy as legacy
import engine.adapters.registry as adapters
from engine.adapters.contracts import DetectionRequest, OcrRequest
from engine.adapters.identity import resolve_execution_identity
from engine.blocks.reading import VisionReading
from engine.compiler import compile_pipeline
from engine.runtime.executor import execute_image
from engine.runtime.values import ExecutionState
from spec.models import Detection, FrameResult, PipelineSpec


def detector_graph() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Adapter test",
        "inputs": {"source": {"type": "image_folder", "path": "media"}}, "blocks": [
            {"id": "f", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
            {"id": "roi", "type": "crop", "params": {"box": [.2, .1, .8, .9]}, "in": {"image": "$f.frame"}},
            {"id": "size", "type": "resize", "params": {"width": 120, "height": 160}, "in": {"image": "$roi.image"}},
            {"id": "d", "type": "detect", "params": {"model": "fixture-color-v1", "classes": ["pallet"]}, "in": {"image": "$size.image"}},
            {"id": "count", "type": "count_per_zone", "in": {"dets": "$d.dets"}},
            {"id": "rule", "type": "rule", "params": {"when": "count >= 1"}, "in": {"value": "$count.counts"}},
            {"id": "out", "type": "sink_event", "in": {"event": "$rule.event"}},
        ]})


def test_input_observations_and_crop_resize_mapping_are_applied_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = Detection(label="pallet", confidence=.7, box=[.1, .2, .6, .8])
    monkeypatch.setattr(legacy, "detect", lambda *args: [original])
    result = execute_image(compile_pipeline(detector_graph(), tmp_path), Image.new("RGB", (100, 100)),
                           "synthetic.png", 0, ExecutionState())
    assert result.detections[0].box == pytest.approx([.26, .26, .56, .74])
    assert original.box == [.1, .2, .6, .8]
    assert result.counts == {"all": 1}
    assert result.events == [{"type": "count_rule", "zone": "all", "count": 1, "when": "count >= 1", "held_s": 0}]
    assert len(result.inferences) == 1
    evidence = result.inferences[0]
    assert evidence.block_id == "d" and evidence.input_to_frame == (.2, .1, .6, .8)
    assert evidence.result.input_size == (120, 160)
    assert evidence.result.detections[0].box == (.1, .2, .6, .8)
    assert evidence.result.identity.identity_scope == "synthetic_code"
    assert evidence.result.timing.total_ms >= 0 and evidence.result.timing.inference_ms is None


def test_legacy_frame_records_load_without_fabricated_evidence() -> None:
    frame = FrameResult.model_validate({"image_path": "old.png", "texts": ["ABC-990"]})
    assert frame.inferences == []
    assert FrameResult.model_validate_json(frame.model_dump_json()) == frame


def test_native_text_duplicates_and_homoglyphs_remain_in_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = tmp_path / "bridge"
    bridge.write_bytes(b"synthetic-bridge")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    monkeypatch.setattr(legacy, "read_native", lambda image: VisionReading(
        texts=["ABC-990", "ABC-990", "\u0425ABC-990Y"], barcodes=["001234"]))
    spec = detector_graph()
    spec.blocks = spec.blocks[:1]
    from spec.models import BlockSpec
    spec.blocks.extend([BlockSpec.model_validate({"id": "read", "type": "ocr", "in": {"image": "$f.frame"}}),
                        BlockSpec.model_validate({"id": "code", "type": "barcode", "in": {"image": "$f.frame"}})])
    result = execute_image(compile_pipeline(spec, tmp_path), Image.new("RGB", (100, 50)), "text.png", 0, ExecutionState())
    assert result.texts == ["ABC-990", "\u0425ABC-990Y", "001234"]
    observations = result.inferences[0].result.readings
    assert [r.text for r in observations] == ["ABC-990", "ABC-990", "\u0425ABC-990Y"]
    assert all(r.box is None and r.confidence is None and r.polygon is None for r in observations)
    assert result.inferences[1].result.readings[0].kind == "barcode"
    assert FrameResult.model_validate_json(result.model_dump_json()) == result


def test_missing_bridge_can_be_authored_but_cannot_execute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISION_APP_BINARY", raising=False)
    spec = detector_graph()
    spec.blocks = spec.blocks[:1]
    from spec.models import BlockSpec
    spec.blocks.append(BlockSpec.model_validate({"id": "read", "type": "ocr", "in": {"image": "$f.frame"}}))
    compiled = compile_pipeline(spec, tmp_path)
    assert compiled.inference_identities["read"].unavailable_artifacts == ["native_bridge"]
    with pytest.raises(adapters.InferenceAborted, match="missing local artifacts"):
        execute_image(compiled, Image.new("RGB", (20, 20)), "text.png", 0, ExecutionState())


def test_bridge_change_after_compile_stops_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = tmp_path / "bridge"
    bridge.write_bytes(b"bridge-1")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    expected = resolve_execution_identity(OcrRequest()).identity_hash
    bridge.write_bytes(b"bridge-2")
    def must_not_run(image: Image.Image) -> VisionReading:
        raise AssertionError("Stale native bridge was invoked")
    monkeypatch.setattr(legacy, "read_native", must_not_run)
    with pytest.raises(adapters.InferenceAborted, match="changed after compilation"):
        adapters.run_inference(Image.new("RGB", (20, 20)), OcrRequest(), expected_identity_hash=expected)


def test_deadline_and_cancellation_discard_late_results(monkeypatch: pytest.MonkeyPatch) -> None:
    request = DetectionRequest(model_id="fixture-color-v1", classes=["pallet"], min_conf=.2)
    cancelled = threading.Event()
    def cancel_during_call(image: Image.Image, ignored: object) -> tuple[list[object], list[object]]:
        cancelled.set()
        return [], []
    monkeypatch.setattr(adapters, "execute_legacy", cancel_during_call)
    with pytest.raises(adapters.InferenceAborted, match="cancelled"):
        adapters.run_inference(Image.new("RGB", (20, 20)), request, cancelled=cancelled)
    with pytest.raises(adapters.InferenceAborted, match="deadline"):
        adapters.run_inference(Image.new("RGB", (20, 20)), request, deadline_monotonic_s=time.monotonic() - 1)


def test_pixels_are_owned_during_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    source = Image.new("RGB", (20, 20), "white")
    request = DetectionRequest(model_id="fixture-color-v1", classes=["pallet"], min_conf=.2)
    def mutate_source(image: Image.Image, ignored: object) -> tuple[list[object], list[object]]:
        source.paste("black", (0, 0, 20, 20))
        assert image.getpixel((0, 0)) == (255, 255, 255)
        return [], []
    monkeypatch.setattr(adapters, "execute_legacy", mutate_source)
    first = adapters.run_inference(source, request)
    monkeypatch.setattr(adapters, "execute_legacy", lambda image, request: ([], []))
    second = adapters.run_inference(source, request)
    assert first.input_pixels_sha256 != second.input_pixels_sha256
