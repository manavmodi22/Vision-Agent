"""Versioned adapter evidence; coordinates are relative to the adapter input."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Coordinate = Annotated[float, Field(ge=0, le=1)]
Box = tuple[Coordinate, Coordinate, Coordinate, Coordinate]
Point = tuple[Coordinate, Coordinate]
Milliseconds = Annotated[float, Field(ge=0)]


class InferenceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Geometry(InferenceContract):
    box: Box | None = None
    polygon: list[Point] | None = Field(default=None, min_length=3, max_length=256)

    @model_validator(mode="after")
    def valid_geometry(self) -> Geometry:
        if self.box and (self.box[0] >= self.box[2] or self.box[1] >= self.box[3]):
            raise ValueError("Observation boxes must have positive area")
        if self.polygon:
            points = self.polygon
            area = sum(x * points[(i + 1) % len(points)][1]
                       - points[(i + 1) % len(points)][0] * y for i, (x, y) in enumerate(points))
            if abs(area) < 1e-8:
                raise ValueError("Observation polygons must have positive area")
            envelope = (min(p[0] for p in points), min(p[1] for p in points),
                        max(p[0] for p in points), max(p[1] for p in points))
            if self.box is None:
                self.box = envelope
            elif any(abs(a - b) > 1e-7 for a, b in zip(self.box, envelope, strict=True)):
                raise ValueError("Observation box must be its polygon envelope")
        return self


class DetectionObservation(Geometry):
    label: str = Field(min_length=1, max_length=256)
    confidence: float = Field(ge=0, le=1)
    box: Box


class TextObservation(Geometry):
    text: str = Field(max_length=16384)
    kind: Literal["ocr", "barcode"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    symbology: str | None = Field(default=None, max_length=80)


class ExecutionIdentity(InferenceContract):
    capability_id: str
    model_id: str
    adapter_id: str
    identity_scope: Literal["local_artifacts_verified", "system_framework_versioned", "synthetic_code"]
    artifact_hashes: dict[str, SHA256]
    unavailable_artifacts: list[str] = Field(default_factory=list)
    adapter_code_sha256: SHA256
    runtime_manifest_sha256: SHA256
    system_identity: dict[str, str]
    provider: str
    config_sha256: SHA256
    identity_hash: SHA256


class InferenceTiming(InferenceContract):
    total_ms: Milliseconds
    startup_ms: Milliseconds | None = None
    load_ms: Milliseconds | None = None
    preprocess_ms: Milliseconds | None = None
    inference_ms: Milliseconds | None = None
    postprocess_ms: Milliseconds | None = None
    transport_ms: Milliseconds | None = None
    model_cached: bool | None = None


class InferenceResult(InferenceContract):
    schema_version: Literal[1] = 1
    task: Literal["detection", "ocr", "barcode"]
    input_size: tuple[Annotated[int, Field(gt=0, le=32768)], Annotated[int, Field(gt=0, le=32768)]]
    input_pixels_sha256: SHA256
    detections: list[DetectionObservation] = Field(default_factory=list, max_length=10000)
    readings: list[TextObservation] = Field(default_factory=list, max_length=10000)
    identity: ExecutionIdentity
    timing: InferenceTiming
    warnings: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def consistent_task(self) -> InferenceResult:
        if self.task == "detection" and self.readings:
            raise ValueError("Detection adapters cannot return readings")
        if self.task != "detection" and (self.detections or any(r.kind != self.task for r in self.readings)):
            raise ValueError("Reader observations must match the requested task")
        if sum(len(r.text.encode("utf-8")) for r in self.readings) > 1024 * 1024:
            raise ValueError("Adapter text output exceeds 1 MiB")
        return self


class BlockInference(InferenceContract):
    block_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    result: InferenceResult
    # Adapter input -> original frame: x'=offset_x + x*scale_x (same for y).
    input_to_frame: tuple[float, float, float, float] = (0, 0, 1, 1)

    @model_validator(mode="after")
    def valid_transform(self) -> BlockInference:
        x, y, sx, sy = self.input_to_frame
        if not all(math.isfinite(v) for v in self.input_to_frame) or min(x, y) < 0 or min(sx, sy) <= 0:
            raise ValueError("Invalid adapter input transform")
        if x + sx > 1 + 1e-8 or y + sy > 1 + 1e-8:
            raise ValueError("Adapter input transform exceeds the original frame")
        return self
