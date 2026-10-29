"""Native Apple Vision subprocess boundary. No shell or fallback OCR."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from pydantic import Field

from spec.models import Contract


class VisionReading(Contract):
    texts: list[str] = Field(default_factory=list)
    barcodes: list[str] = Field(default_factory=list)


def read_native(image: Image.Image) -> VisionReading:
    binary = os.environ.get("VISION_APP_BINARY")
    if not binary or not Path(binary).is_file():
        raise ValueError("Apple Vision requires the native app. Build it and set VISION_APP_BINARY.")
    with tempfile.TemporaryDirectory(prefix="vision-reading-") as directory:
        image_path = Path(directory) / "frame.png"
        image.save(image_path)
        try:
            process = subprocess.run([binary, "--analyze-image", str(image_path)],
                                     capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Apple Vision bridge failed: {exc}") from exc
        if process.returncode:
            raise ValueError(f"Apple Vision failed: {process.stderr.strip()[:500]}")
        return VisionReading.model_validate_json(process.stdout)
