"""Pipeline format 0.1. Boxes are normalized top-left xyxy coordinates."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from spec.inference import BlockInference


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class Zone(Contract):
    id: str = Field(min_length=1, max_length=80)
    polygon: list[tuple[float, float]] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def valid_polygon(cls, value: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if any(not math.isfinite(c) or c < 0 or c > 1 for point in value for c in point):
            raise ValueError("Zone coordinates must be finite normalized values in [0, 1]")
        area = sum(value[i][0] * value[(i + 1) % len(value)][1]
                   - value[(i + 1) % len(value)][0] * value[i][1] for i in range(len(value)))
        if abs(area) < 1e-8:
            raise ValueError("Zone polygon must have positive area")
        return value


class SourceSpec(Contract):
    type: Literal["image_folder", "image_file", "video_file", "camera", "screen_capture"]
    path: str = Field(min_length=1)


class BlockSpec(Contract):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    type: str = Field(min_length=1)
    params: dict[str, JsonValue] = Field(default_factory=dict)
    inputs: dict[str, str] = Field(default_factory=dict, alias="in")


class EvalConfig(Contract):
    set: str = "eval/default"
    metric: Literal["count_mae", "precision", "recall", "text_accuracy"] = "count_mae"
    target: float = Field(default=0.5, ge=0)

    @model_validator(mode="after")
    def valid_target(self) -> EvalConfig:
        if self.metric != "count_mae" and self.target > 1:
            raise ValueError("Precision, recall and text_accuracy targets must be in [0, 1]")
        return self


class PipelineSpec(Contract):
    spec_version: Literal["0.1"] = "0.1"
    name: str = Field(min_length=1, max_length=120)
    inputs: dict[str, SourceSpec]
    blocks: list[BlockSpec] = Field(min_length=1, max_length=64)
    eval: EvalConfig = Field(default_factory=EvalConfig)

    @field_validator("inputs")
    @classmethod
    def single_source(cls, value: dict[str, SourceSpec]) -> dict[str, SourceSpec]:
        if set(value) != {"source"}:
            raise ValueError("Version 0.1 requires exactly one input named source")
        return value


class TaskBrief(Contract):
    goal: str = Field(min_length=1)
    objects: list[str] = Field(default_factory=list)
    zones: list[Zone] = Field(default_factory=list)
    metric: Literal["count_mae", "precision", "recall", "text_accuracy"] = "count_mae"
    threshold: float = Field(default=0.5, ge=0)
    output: str = "events"
    use_case: Literal["custom", "pallets", "damage", "labels"] = "custom"
    confirmed: bool = False


class Detection(Contract):
    label: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    box: list[float] = Field(min_length=4, max_length=4)
    zone: str | None = None

    @field_validator("box")
    @classmethod
    def valid_box(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in value):
            raise ValueError("Boxes must use finite normalized coordinates in [0, 1]")
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("Boxes must have positive width and height")
        return value


class JudgementEvidence(Contract):
    label: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1500)
    confidence: float = Field(ge=0, le=1)
    model: str
    base_url: str
    image_sha256: str
    model_identity_hash: str
    identity_scope: Literal["local_weights_verified", "server_metadata_only"]
    weights_sha256: str | None = None
    box: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0], min_length=4, max_length=4)
    input_size: tuple[int, int]
    sent_size: tuple[int, int]
    elapsed_s: float = Field(ge=0)
    attempts: int = Field(ge=1, le=3)
    status: Literal["model_hypothesis"] = "model_hypothesis"
    warnings: list[str] = Field(default_factory=list)


class FrameResult(Contract):
    image_path: str
    detections: list[Detection] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    texts: list[str] = Field(default_factory=list)
    events: list[dict[str, JsonValue]] = Field(default_factory=list)
    elapsed_ms: float = Field(default=0, ge=0)
    timestamp_s: float = Field(default=0, ge=0)
    judgements: list[JudgementEvidence] = Field(default_factory=list)
    inferences: list[BlockInference] = Field(default_factory=list, max_length=64)


class RunResult(Contract):
    frames: list[FrameResult]
    elapsed_s: float = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)


class ProposalEvidence(Contract):
    source: Literal["model_proposal"] = "model_proposal"
    model_id: str
    spec_hash: str
    image_sha256: str
    created_at: str
    status: Literal["unverified_hypothesis"] = "unverified_hypothesis"


class Annotation(Contract):
    image_path: str
    detections: list[Detection] = Field(default_factory=list)
    reviewed: bool = False
    expected_texts: list[str] = Field(default_factory=list)
    proposal: ProposalEvidence | None = None


class EvalDataset(Contract):
    id: str = Field(min_length=1)
    annotations: list[Annotation] = Field(default_factory=list)


class EvaluationResult(Contract):
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    count_mae: float = Field(ge=0)
    passed: bool
    metric: str
    target: float
    sample_count: int = Field(ge=1)
    failures: list[dict[str, JsonValue]] = Field(default_factory=list)
    spec_hash: str
    dataset_hash: str
    text_accuracy: float = Field(default=0, ge=0, le=1)
    character_error_rate: float | None = Field(default=None, ge=0)
    word_error_rate: float | None = Field(default=None, ge=0)
    text_normalization: str | None = None
    text_error_counts: dict[str, int | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
