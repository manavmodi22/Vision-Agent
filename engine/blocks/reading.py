"""Native Apple Vision subprocess boundary. No shell or fallback OCR."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image
from pydantic import Field, model_validator

from engine.blocks.reading_identity import READING_REQUEST_POLICY_VERSION
from spec.inference import TextObservation
from spec.models import Contract


class VisionReading(Contract):
    """Historical string-only payload; retained for saved evidence and fixtures."""

    texts: list[str] = Field(default_factory=list)
    barcodes: list[str] = Field(default_factory=list)


class NativeVisionReading(VisionReading):
    schema_version: Literal[2]
    request_policy: str
    coordinate_space: Literal["normalized_top_left"]
    input_size: tuple[Annotated[int, Field(gt=0, le=32768)], Annotated[int, Field(gt=0, le=32768)]]
    readings: list[TextObservation] = Field(max_length=10000)
    warnings: list[Annotated[str, Field(max_length=1000)]] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_native_projection(self) -> NativeVisionReading:
        if self.request_policy != READING_REQUEST_POLICY_VERSION:
            raise ValueError("Native OCR request policy differs from the engine policy")
        if self.texts != [row.text for row in self.readings if row.kind == "ocr"]:
            raise ValueError("Native OCR text projection differs from its observations")
        if self.barcodes != [row.text for row in self.readings if row.kind == "barcode"]:
            raise ValueError("Native barcode projection differs from its observations")
        if sum(len(row.text.encode("utf-8")) for row in self.readings) > 1024 * 1024:
            raise ValueError("Native text exceeds the adapter output budget")
        return self


def read_native(image: Image.Image) -> NativeVisionReading:
    binary = os.environ.get("VISION_APP_BINARY")
    if not binary or not Path(binary).is_file():
        raise ValueError("Apple Vision requires the native app. Build it and set VISION_APP_BINARY.")
    with tempfile.TemporaryDirectory(prefix="vision-reading-") as directory:
        image_path = Path(directory) / "frame.png"
        # The adapter contract refers to these pixels, not inherited EXIF orientation.
        rgb = image.convert("RGB")
        Image.frombytes("RGB", rgb.size, rgb.tobytes()).save(image_path)
        try:
            process = subprocess.run([binary, "--analyze-image", str(image_path), "--protocol", "2"],
                                     capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Apple Vision bridge failed: {exc}") from exc
        if process.returncode:
            raise ValueError(f"Apple Vision protocol 2 failed: {process.stderr.strip()[:500]}")
        if len(process.stdout.encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("Native response exceeds the adapter output budget")
        reading = NativeVisionReading.model_validate_json(process.stdout)
        if reading.input_size != image.size:
            raise ValueError("Native reading geometry refers to different input dimensions")
        return reading
