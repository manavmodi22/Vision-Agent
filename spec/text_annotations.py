"""Human text-region labels; geometry is normalized oriented full-frame RGB."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from spec.inference import SHA256, Geometry, InferenceContract, Point, TextObservation


class TextRegionSeed(InferenceContract):
    """Original model observation retained as provenance, never as review approval."""
    source: Literal["model_reading"] = "model_reading"
    model_id: str = Field(min_length=1, max_length=256)
    adapter_id: str = Field(min_length=1, max_length=256)
    identity_hash: SHA256
    block_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    observation_index: int = Field(ge=0, le=9999)
    observation: TextObservation
    input_to_frame: tuple[float, float, float, float]
    image_sha256: SHA256
    created_at: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_source(self) -> TextRegionSeed:
        x, y, sx, sy = self.input_to_frame
        if (not all(math.isfinite(v) for v in self.input_to_frame)
                or min(x, y) < 0 or min(sx, sy) <= 0 or x + sx > 1 + 1e-8 or y + sy > 1 + 1e-8):
            raise ValueError("Invalid seed adapter input transform")
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Seed creation time must be an ISO timestamp") from exc
        if created.tzinfo is None:
            raise ValueError("Seed creation time must include its timezone")
        return self


class TextRegion(Geometry):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    polygon: list[Point] = Field(min_length=4, max_length=4)
    transcript: str | None = Field(default=None, max_length=16384)
    seed: TextRegionSeed | None = None

    @model_validator(mode="after")
    def convex_quadrilateral(self) -> TextRegion:
        points = self.polygon
        turns = []
        for index, a in enumerate(points):
            b, c = points[(index + 1) % 4], points[(index + 2) % 4]
            turns.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
        if not (all(turn > 1e-8 for turn in turns) or all(turn < -1e-8 for turn in turns)):
            raise ValueError("Text regions must be simple convex quadrilaterals with four distinct corners")
        return self
