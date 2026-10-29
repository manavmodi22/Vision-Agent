"""Typed engine requests. These do not add model choices or graph ports."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from spec.inference import InferenceContract


class DetectionRequest(InferenceContract):
    task: Literal["detection"] = "detection"
    model_id: str
    classes: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(min_length=1, max_length=64)
    min_conf: float = Field(ge=0, le=1)


class OcrRequest(InferenceContract):
    task: Literal["ocr"] = "ocr"
    model_id: Literal["apple-vision"] = "apple-vision"
    languages: list[str] = Field(default_factory=lambda: ["en-US"])

    @field_validator("languages")
    @classmethod
    def supported_language(cls, value: list[str]) -> list[str]:
        if value != ["en-US"]:
            raise ValueError("This native bridge supports only en-US recognition")
        return value


class BarcodeRequest(InferenceContract):
    task: Literal["barcode"] = "barcode"
    model_id: Literal["apple-vision"] = "apple-vision"


InferenceRequest = Annotated[DetectionRequest | OcrRequest | BarcodeRequest, Field(discriminator="task")]
