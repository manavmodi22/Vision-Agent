"""Introspectable contracts for blocks implemented by the executor."""
import builtins
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from engine.blocks.params import (
    CountParams,
    CropParams,
    DetectParams,
    EmptyParams,
    FrameSampleParams,
    MatchParams,
    ReadingParams,
    ResizeParams,
    RuleParams,
    SinkEventParams,
    VLMJudgeParams,
    ZoneFilterParams,
)
from spec.models import Contract

PortType = Literal["frames", "image", "detections", "counts", "text", "event", "judgement"]


@dataclass(frozen=True)
class BlockDefinition:
    type: str
    description: str
    params: builtins.type[Contract]
    inputs: dict[str, PortType]
    outputs: dict[str, PortType]


DEFINITIONS = [
    BlockDefinition("frame_sample", "Sample frames at a bounded rate.", FrameSampleParams,
                    {"frames": "frames"}, {"frame": "image"}),
    BlockDefinition("detect", "Run a locally installed detector.", DetectParams,
                    {"image": "image"}, {"dets": "detections"}),
    BlockDefinition("detect_open_vocab", "Detect text-prompted classes using local OWLv2.", DetectParams,
                    {"image": "image"}, {"dets": "detections"}),
    BlockDefinition("zone_filter", "Keep objects whose center is inside a polygon.", ZoneFilterParams,
                    {"dets": "detections"}, {"dets": "detections"}),
    BlockDefinition("count_per_zone", "Count detections in each named zone.", CountParams,
                    {"dets": "detections"}, {"counts": "counts"}),
    BlockDefinition("rule", "Compare zone counts using a small safe expression language.", RuleParams,
                    {"value": "counts"}, {"event": "event"}),
    BlockDefinition("sink_event", "Emit local evidence events; delivery is separately approved.", SinkEventParams,
                    {"event": "event"}, {"event": "event"}),
    BlockDefinition("ocr", "Read text with native Apple Vision.", ReadingParams,
                    {"image": "image"}, {"text": "text"}),
    BlockDefinition("barcode", "Read barcode payloads with native Apple Vision.", EmptyParams,
                    {"image": "image"}, {"text": "text"}),
    BlockDefinition("match", "Compare recognized text with an expected value.", MatchParams,
                    {"text": "text"}, {"event": "event"}),
    BlockDefinition("vlm_judge", "Ask a configured local vision model for a bounded evidence judgement.", VLMJudgeParams,
                    {"image": "image"}, {"judgement": "judgement", "text": "text", "event": "event"}),
    BlockDefinition("resize", "Resize input pixels; normalized boxes remain unchanged.", ResizeParams,
                    {"image": "image"}, {"image": "image"}),
    BlockDefinition("crop", "Crop a normalized rectangle and preserve coordinate transforms.", CropParams,
                    {"image": "image"}, {"image": "image"}),
]
REGISTRY = {definition.type: definition for definition in DEFINITIONS}


def block_schema(block_type: str) -> dict[str, JsonValue]:
    definition = REGISTRY.get(block_type)
    if definition is None:
        raise ValueError(f"Unsupported block: {block_type}")
    return {
        "type": definition.type, "description": definition.description,
        "params": definition.params.model_json_schema(),
        "inputs": dict(definition.inputs), "outputs": dict(definition.outputs),
    }


def list_blocks() -> list[dict[str, JsonValue]]:
    return [block_schema(item.type) for item in DEFINITIONS]
