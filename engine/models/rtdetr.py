"""Permissive pretrained RT-DETRv2 and its locally specialized descendants."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from engine.models.artifacts import assert_model_fingerprint, model_content_fingerprint
from engine.models.manager import ModelUnavailable, model_directory, rtdetr_path
from spec.models import Detection

if TYPE_CHECKING:
    from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection


def model_path(model_id: str) -> Path:
    return rtdetr_path() if model_id == "rtdetr-v2-r18" else model_directory() / model_id


@lru_cache(maxsize=2)
def _load(path_string: str, model_id: str,
          content_fingerprint: str, device: str) -> tuple[RTDetrImageProcessor, RTDetrV2ForObjectDetection, str]:
    from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection
    path = Path(path_string)
    assert_model_fingerprint(model_id, content_fingerprint)
    try:
        processor = RTDetrImageProcessor.from_pretrained(path, local_files_only=True)
        model = RTDetrV2ForObjectDetection.from_pretrained(path, local_files_only=True, use_safetensors=True)
        model.config.disable_custom_kernels = True
        model.to(device).eval()
        assert_model_fingerprint(model_id, content_fingerprint)
        return processor, model, device
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise ModelUnavailable(f"Failed to load local RT-DETRv2: {exc}") from exc


def detect_rtdetr(image: Image.Image, model_id: str, classes: list[str], min_conf: float) -> list[Detection]:
    import torch
    path = model_path(model_id)
    fingerprint = model_content_fingerprint(model_id)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor, model, device = _load(str(path), model_id, fingerprint, device)
    id2label = model.config.id2label
    if not id2label:
        raise ModelUnavailable("RT-DETRv2 checkpoint has no class mapping")
    supported = set(id2label.values())
    unknown = set(classes) - supported
    if unknown:
        raise ModelUnavailable(f"This RT-DETRv2 checkpoint has not been trained for: {', '.join(sorted(unknown))}. Use open-vocabulary proposals and fine-tune reviewed labels.")
    try:
        inputs = processor(images=image.convert("RGB"), return_tensors="pt").to(device)
        with torch.inference_mode():
            outputs = model(**inputs)
        results = processor.post_process_object_detection(
            outputs, target_sizes=[(image.height, image.width)], threshold=min_conf)
    except (RuntimeError, ValueError, OSError) as exc:
        raise ModelUnavailable(f"RT-DETRv2 inference failed on {device}: {exc}") from exc
    detections: list[Detection] = []
    for score, label, raw_box in zip(results[0]["scores"], results[0]["labels"], results[0]["boxes"], strict=True):
        name = str(id2label[int(label)])
        if name not in classes:
            continue
        values = raw_box.cpu().tolist()
        box = [max(0.0, min(1.0, values[i] / (image.width if i % 2 == 0 else image.height))) for i in range(4)]
        if box[0] < box[2] and box[1] < box[3]:
            detections.append(Detection(label=name, confidence=float(score), box=box))
    assert_model_fingerprint(model_id, fingerprint)
    return detections
