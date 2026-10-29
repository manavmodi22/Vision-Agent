"""Thin projections around existing implementations; no inferred OCR confidence."""
from __future__ import annotations

from PIL import Image

from engine.adapters.contracts import DetectionRequest, InferenceRequest
from engine.blocks.reading import read_native
from engine.models import detect
from spec.inference import DetectionObservation, TextObservation


def execute_legacy(image: Image.Image, request: InferenceRequest) -> tuple[list[DetectionObservation], list[TextObservation]]:
    if isinstance(request, DetectionRequest):
        detections = detect(image, request.model_id, request.classes, request.min_conf)
        return [DetectionObservation(label=d.label, confidence=d.confidence, box=tuple(d.box))  # type: ignore[arg-type]
                for d in detections], []
    reading = read_native(image)
    strings = reading.texts if request.task == "ocr" else reading.barcodes
    return [], [TextObservation(text=value, kind=request.task) for value in strings]
