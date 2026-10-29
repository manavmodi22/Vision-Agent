"""Typed parameters for each executable block; unknown settings are rejected."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from engine.llm_client.contracts import VLMConfig
from spec.models import Contract, Zone


class EmptyParams(Contract):
    pass


class FrameSampleParams(Contract):
    fps: float = Field(default=2, gt=0, le=60)


class DetectParams(Contract):
    model: str = "owlv2-base-patch16"
    classes: list[str] = Field(default_factory=lambda: ["pallet"], min_length=1, max_length=64)
    min_conf: float = Field(default=0.25, ge=0, le=1)


class ZoneFilterParams(Contract):
    zones: str | list[Zone] = "zones/lanes.json"
    include_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("include_ids")
    @classmethod
    def unique_zone_ids(cls, value: list[str]) -> list[str]:
        if any(not name.strip() for name in value) or len(set(value)) != len(value):
            raise ValueError("Selected region names must be nonempty and unique")
        return value


class CountParams(Contract):
    include_unassigned: bool = False


class RuleParams(Contract):
    when: str = Field(default="count >= 1", max_length=100)
    hold_s: float = Field(default=0, ge=0, le=86400)


class SinkEventParams(Contract):
    alert: str | None = None


class MatchParams(Contract):
    expected: str = Field(min_length=1, max_length=256)
    mode: Literal["contains", "exact"] = "contains"
    emit: Literal["all", "matched", "mismatched"] = "all"


class ResizeParams(Contract):
    width: int = Field(default=640, gt=0, le=8192)
    height: int = Field(default=480, gt=0, le=8192)


class CropParams(Contract):
    box: tuple[float, float, float, float]


class ReadingParams(Contract):
    model: Literal["apple-vision", "ppocr-v5-mobile-en"] = "apple-vision"
    languages: list[str] = Field(default_factory=lambda: ["en-US"])


class VLMJudgeParams(VLMConfig):
    question: str = Field(min_length=1, max_length=3000)
    labels: list[str] = Field(min_length=2, max_length=20)

    @field_validator("labels")
    @classmethod
    def unique_labels(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(not item.strip() or len(item) > 80 for item in value):
            raise ValueError("VLM labels must be unique nonempty strings of at most 80 characters")
        return value

    def client_config(self) -> VLMConfig:
        return VLMConfig.model_validate(self.model_dump(exclude={"question", "labels"}))
