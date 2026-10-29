"""Fixed black-image inference subprocess. No user media, download or shell inputs."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import time

from PIL import Image
from pydantic import Field, model_validator

from engine.provisioning.registry import recipe_for
from spec.models import Contract


class SmokeObservation(Contract):
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    elapsed_s: float = Field(ge=0, le=100)
    observation_count: int = Field(ge=0, le=1000)
    execution_identity_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def fixed_input(self) -> SmokeObservation:
        expected = hashlib.sha256(b"RGB\0" + struct.pack(">II", 640, 640) + bytes(640 * 640 * 3)).hexdigest()
        if self.input_sha256 != expected:
            raise ValueError("Validation did not report the fixed generated black input")
        return self


def main() -> None:
    if len(sys.argv) != 2:
        raise ValueError("A reviewed model ID is required")
    from engine.adapters.contracts import DetectionRequest
    from engine.adapters.registry import run_inference
    recipe = recipe_for(sys.argv[1])
    result = run_inference(Image.new("RGB", (640, 640), "black"),
        DetectionRequest(model_id=recipe.model_id, classes=["person"], min_conf=.3),
        deadline_monotonic_s=time.monotonic() + 90)
    print(json.dumps({"input_sha256": result.input_pixels_sha256,
        "elapsed_s": result.timing.total_ms / 1000,
        "observation_count": len(result.detections), "execution_identity_hash": result.identity.identity_hash}))


if __name__ == "__main__":
    main()
