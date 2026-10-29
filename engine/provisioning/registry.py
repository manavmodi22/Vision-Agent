"""Reviewed fixed install recipes; no user URLs, paths, packages or commands."""
from __future__ import annotations

from dataclasses import dataclass

from spec.provisioning import ProvisioningArtifact


@dataclass(frozen=True)
class Recipe:
    model_id: str
    name: str
    revision: str
    artifacts: tuple[ProvisioningArtifact, ...]
    packages: tuple[str, ...] = ("onnxruntime", "numpy", "Pillow", "opencv-python-headless", "pydantic")
    platforms: tuple[str, ...] = ("Darwin", "Linux")
    max_duration_s: int = 600


YOLOX = Recipe(model_id="yolox-s-onnx-coco", name="YOLOX-s ONNX COCO (CPU)",
    revision="6ddff4824372906469a7fae2dc3206c7aa4bbaee",
    artifacts=(
        ProvisioningArtifact(filename="model.onnx",
            source_url="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
            expected_sha256="c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063", expected_bytes=35858002),
        ProvisioningArtifact(filename="LICENSE.txt",
            source_url="https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/6ddff4824372906469a7fae2dc3206c7aa4bbaee/LICENSE",
            expected_sha256="0ec3668d3274bcf29e8a29e9576d5a2cd96fc78d3c5bec4387355a796e5d9088", expected_bytes=11371),
    ))
RECIPES = {YOLOX.model_id: YOLOX}
DOWNLOAD_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "raw.githubusercontent.com"})


def recipe_for(model_id: str) -> Recipe:
    try:
        return RECIPES[model_id]
    except KeyError:
        raise ValueError("This model has no reviewed provisioning recipe; no download was started") from None
