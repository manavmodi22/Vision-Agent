"""Local SSDLite adapter. All parameters load from safetensors, never pickle."""
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, cast

import numpy as np
from PIL import Image

from engine.models.artifacts import assert_model_fingerprint, model_content_fingerprint
from engine.models.local_manifest import read_manifest
from engine.models.manager import model_directory
from spec.models import Detection

if TYPE_CHECKING:
    import torch
    from torchvision.models.detection.ssd import SSD


def make_model(num_classes: int) -> SSD:
    from torchvision.models.detection import ssdlite320_mobilenet_v3_large
    # Both None arguments are intentional: torchvision must not download weights.
    return cast("SSD", ssdlite320_mobilenet_v3_large(weights=None, weights_backbone=None,
                                                    num_classes=num_classes))


def image_tensor(image: Image.Image) -> torch.Tensor:
    import torch
    array = np.asarray(image.convert("RGB"), dtype=np.float32).copy() / 255.0
    return torch.from_numpy(array).permute(2, 0, 1)


@lru_cache(maxsize=2)
def _load(model_id: str, path_string: str, content_fingerprint: str) -> tuple[SSD, tuple[str, ...]]:
    from safetensors import SafetensorError
    from safetensors.torch import load_file

    from engine.models.manager import ModelUnavailable
    assert_model_fingerprint(model_id, content_fingerprint)
    manifest = read_manifest(model_id, model_directory())
    path = model_directory() / model_id / "model.safetensors"
    model = make_model(len(manifest.classes) + 1)
    try:
        model.load_state_dict(load_file(str(path)), strict=True)
    except (OSError, ValueError, RuntimeError, SafetensorError) as exc:
        raise ModelUnavailable(f"Failed to load local detector {model_id}: {exc}") from exc
    model.eval()
    assert_model_fingerprint(model_id, content_fingerprint)
    return model, tuple(manifest.classes)


def detect_ssdlite(image: Image.Image, model_id: str, classes: list[str], min_conf: float) -> list[Detection]:
    import torch
    path = model_directory() / model_id / "model.safetensors"
    fingerprint = model_content_fingerprint(model_id)
    model, trained_classes = _load(model_id, str(path), fingerprint)
    unknown = set(classes) - set(trained_classes)
    if unknown:
        raise ValueError(f"This local detector was not trained for classes: {', '.join(sorted(unknown))}")
    with torch.inference_mode():
        outputs = model([image_tensor(image)])[0]
    result: list[Detection] = []
    for raw_box, label, score in zip(outputs["boxes"], outputs["labels"], outputs["scores"], strict=True):
        confidence, index = float(score), int(label) - 1
        if confidence < min_conf or not 0 <= index < len(trained_classes):
            continue
        name = trained_classes[index]
        if name not in classes:
            continue
        values = raw_box.tolist()
        box = [max(0.0, min(1.0, values[i] / (image.width if i % 2 == 0 else image.height))) for i in range(4)]
        if box[0] < box[2] and box[1] < box[3]:
            result.append(Detection(label=name, confidence=confidence, box=box))
    assert_model_fingerprint(model_id, fingerprint)
    return result
