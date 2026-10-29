"""Optional OWLv2 inference from a trusted local model snapshot only."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from engine.models.artifacts import assert_model_fingerprint, model_content_fingerprint
from engine.models.manager import ModelUnavailable, owlv2_path, validate_model
from spec.models import Detection

if TYPE_CHECKING:
    from transformers import Owlv2ForObjectDetection, Owlv2Processor


@lru_cache(maxsize=1)
def _load(path_string: str, content_fingerprint: str, device: str) -> tuple[Owlv2Processor, Owlv2ForObjectDetection, str]:
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    validate_model("owlv2-base-patch16")
    path = str(Path(path_string))
    assert_model_fingerprint("owlv2-base-patch16", content_fingerprint)
    try:
        processor = Owlv2Processor.from_pretrained(path, local_files_only=True, use_fast=False)
        model = Owlv2ForObjectDetection.from_pretrained(path, local_files_only=True, use_safetensors=True)
        model.to(device).eval()
        assert_model_fingerprint("owlv2-base-patch16", content_fingerprint)
        return processor, model, device
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        raise ModelUnavailable(f"Failed to load local OWLv2: {exc}") from exc


def detect_owlv2(image: Image.Image, classes: list[str], min_conf: float) -> list[Detection]:
    import torch

    path = owlv2_path()
    fingerprint = model_content_fingerprint("owlv2-base-patch16")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    processor, model, device = _load(str(path), fingerprint, device)
    try:
        inputs = processor(text=[classes], images=image.convert("RGB"), return_tensors="pt").to(device)
        with torch.inference_mode():
            output = model(**inputs)
        results = processor.post_process_object_detection(  # type: ignore[no-untyped-call,unused-ignore]
            outputs=output, threshold=min_conf,
            target_sizes=torch.tensor([image.size[::-1]], device=device))
    except (ImportError, RuntimeError, ValueError, OSError) as exc:
        raise ModelUnavailable(f"OWLv2 inference failed ({device}): {exc}") from exc
    result: list[Detection] = []
    width, height = image.size
    for score, label, raw_box in zip(results[0]["scores"], results[0]["labels"], results[0]["boxes"], strict=True):
        values = raw_box.cpu().tolist()
        box = [max(0.0, min(1.0, values[i] / (width if i % 2 == 0 else height))) for i in range(4)]
        if box[0] < box[2] and box[1] < box[3]:
            result.append(Detection(label=classes[int(label)], confidence=float(score), box=box))
    assert_model_fingerprint("owlv2-base-patch16", fingerprint)
    return result
