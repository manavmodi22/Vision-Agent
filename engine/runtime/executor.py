"""Type-directed execution of compiled, registered blocks only."""
from __future__ import annotations

import time
from pathlib import Path
from typing import cast

from PIL import Image, ImageOps
from pydantic import JsonValue

from engine.adapters.registry import run_inference
from engine.adapters.requests import request_for_block
from engine.blocks.logic import parse_rule
from engine.blocks.params import (
    CountParams,
    CropParams,
    MatchParams,
    ResizeParams,
    RuleParams,
    SinkEventParams,
    VLMJudgeParams,
)
from engine.blocks.spatial import assign_zones
from engine.compiler import CompiledPipeline
from engine.models.artifacts import content_hash
from engine.runtime.values import (
    CountsValue,
    DetectionsValue,
    EventValue,
    ExecutionState,
    ImageValue,
    JudgementValue,
    PortValue,
    TextValue,
)
from spec.inference import BlockInference
from spec.models import BlockSpec, Detection, FrameResult, TextComparison


def execute_frame(compiled: CompiledPipeline, path: Path, timestamp: float,
                  state: ExecutionState) -> FrameResult:
    started = time.perf_counter()
    source_hash = content_hash(path)
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read image {path.name}: {exc}") from exc
    result = execute_image(compiled, image, str(path), timestamp, state)
    if content_hash(path) != source_hash:
        raise ValueError("Source image changed during inference; discard this preview and run it again")
    result.source_image_sha256 = source_hash
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


def execute_image(compiled: CompiledPipeline, image: Image.Image, image_path: str,
                  timestamp: float, state: ExecutionState) -> FrameResult:
    """Execute owned RGB pixels; native live ingress never needs a temporary file."""
    started = time.perf_counter()
    values: dict[str, PortValue] = {"$inputs.source": ImageValue(image)}
    result = FrameResult(image_path=image_path, timestamp_s=timestamp)
    for block in compiled.blocks:
        inputs = {name: values[ref] for name, ref in block.inputs.items()}
        if block.type == "match":
            comparison, event = compare_text(block.id, cast(TextValue, inputs["text"]),
                                             cast(MatchParams, compiled.params[block.id]))
            result.comparisons.append(comparison)
            output: dict[str, PortValue] = {"event": event}
        else:
            output = execute_block(block, inputs, compiled, timestamp, state)
        for port, value in output.items():
            values[f"${block.id}.{port}"] = value
            if isinstance(value, (DetectionsValue, TextValue)) and value.inference is not None:
                result.inferences.append(value.inference)
            if isinstance(value, DetectionsValue):
                result.detections = value.detections
            elif isinstance(value, CountsValue):
                result.counts = value.counts
            elif isinstance(value, TextValue):
                result.texts.extend(value.texts)
            elif isinstance(value, JudgementValue):
                result.judgements.append(value.judgement)
            elif isinstance(value, EventValue) and block.type == "sink_event":
                result.events.extend(value.events)
    result.texts = list(dict.fromkeys(result.texts))
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


def compare_text(block_id: str, text: TextValue, params: MatchParams) -> tuple[TextComparison, EventValue]:
    """Compute a check once; event filtering never removes the observation."""
    matched = (params.expected in text.texts if params.mode == "exact"
               else params.expected in " ".join(text.texts))
    comparison = TextComparison(block_id=block_id, expected=params.expected, observed=list(text.texts),
                                mode=params.mode, matched=matched)
    if (params.emit == "matched" and not matched) or (params.emit == "mismatched" and matched):
        return comparison, EventValue([])
    return comparison, EventValue([{"type": "label_check", "matched": matched,
                                    "expected": params.expected, "observed": list(text.texts)}])


def execute_block(block: BlockSpec, inputs: dict[str, PortValue], compiled: CompiledPipeline,
                  timestamp: float, state: ExecutionState) -> dict[str, PortValue]:
    params = compiled.params[block.id]
    if block.type == "frame_sample":
        return {"frame": inputs["frames"]}
    if block.type in {"detect", "detect_open_vocab"}:
        image = cast(ImageValue, inputs["image"])
        request = request_for_block(block)
        assert request is not None
        inference = run_inference(image.image, request,
            expected_identity_hash=compiled.inference_identities[block.id].identity_hash)
        ox, oy, sx, sy = image.transform
        detections = [Detection(label=d.label, confidence=d.confidence,
                      box=[ox + d.box[0] * sx, oy + d.box[1] * sy,
                           ox + d.box[2] * sx, oy + d.box[3] * sy]) for d in inference.detections]
        return {"dets": DetectionsValue(detections, inference=BlockInference(
            block_id=block.id, result=inference, input_to_frame=image.transform))}
    if block.type == "zone_filter":
        zone_input = cast(DetectionsValue, inputs["dets"])
        zones = compiled.zones[block.id]
        return {"dets": DetectionsValue(assign_zones(zone_input.detections, zones), [z.id for z in zones])}
    if block.type == "count_per_zone":
        return {"counts": count_detections(cast(DetectionsValue, inputs["dets"]), cast(CountParams, params))}
    if block.type == "rule":
        counts = cast(CountsValue, inputs["value"])
        rule_params = cast(RuleParams, params)
        rule = parse_rule(rule_params.when)
        emitted_events: list[dict[str, JsonValue]] = []
        for zone, count in counts.counts.items():
            key = (block.id, zone)
            if rule.matches(count):
                since = state.true_since.setdefault(key, timestamp)
                if timestamp - since >= rule_params.hold_s:
                    emitted_events.append({"type": "count_rule", "zone": zone, "count": count,
                                   "when": rule_params.when, "held_s": timestamp - since})
            else:
                state.true_since.pop(key, None)
        return {"event": EventValue(emitted_events)}
    if block.type == "sink_event":
        events = cast(EventValue, inputs["event"])
        sink_params = cast(SinkEventParams, params)
        if sink_params.alert:
            return {"event": EventValue([{**event, "alert_target": sink_params.alert} for event in events.events])}
        return {"event": events}
    if block.type in {"ocr", "barcode"}:
        image = cast(ImageValue, inputs["image"])
        request = request_for_block(block)
        assert request is not None
        inference = run_inference(image.image, request,
            expected_identity_hash=compiled.inference_identities[block.id].identity_hash)
        return {"text": TextValue([reading.text for reading in inference.readings], BlockInference(
            block_id=block.id, result=inference, input_to_frame=image.transform))}
    if block.type == "match":
        _, event = compare_text(block.id, cast(TextValue, inputs["text"]), cast(MatchParams, params))
        return {"event": event}
    if block.type == "vlm_judge":
        from engine.llm_client import judge_image
        image = cast(ImageValue, inputs["image"])
        vlm = cast(VLMJudgeParams, params)
        judgement = judge_image(image.image, vlm.client_config(), vlm.question, vlm.labels)
        if judgement.model_identity_hash != compiled.vlm_identities[block.id].identity_hash:
            raise ValueError("The VLM identity changed after pipeline compilation; rebuild and evaluate")
        ox, oy, sx, sy = image.transform
        judgement.box = [ox, oy, ox + sx, oy + sy]
        return {"judgement": JudgementValue(judgement), "text": TextValue([judgement.label]),
                "event": EventValue([{"type": "vlm_judgement", **judgement.model_dump(mode="json")}])}
    if block.type == "resize":
        image = cast(ImageValue, inputs["image"])
        size = cast(ResizeParams, params)
        return {"image": ImageValue(image.image.resize((size.width, size.height)), image.transform)}
    if block.type == "crop":
        image = cast(ImageValue, inputs["image"])
        x0, y0, x1, y1 = cast(CropParams, params).box
        width, height = image.image.size
        # Use actual pixel bounds for the coordinate transform after integer rounding.
        left, top, right, bottom = int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)
        if right <= left or bottom <= top:
            raise ValueError("Crop rectangle is smaller than a pixel on this image")
        ox, oy, sx, sy = image.transform
        transform = (ox + left / width * sx, oy + top / height * sy,
                     (right - left) / width * sx, (bottom - top) / height * sy)
        return {"image": ImageValue(image.image.crop((left, top, right, bottom)), transform)}
    raise ValueError(f"No executor for block '{block.type}'")


def count_detections(value: DetectionsValue, params: CountParams) -> CountsValue:
    counts = dict.fromkeys(value.zones, 0)
    if not value.zones:
        counts["all"] = len(value.detections)
    else:
        for detection in value.detections:
            if detection.zone:
                counts[detection.zone] = counts.get(detection.zone, 0) + 1
            elif params.include_unassigned:
                counts["unassigned"] = counts.get("unassigned", 0) + 1
    return CountsValue(counts)
