"""Thin projections around existing implementations; no inferred OCR confidence."""
from __future__ import annotations

from PIL import Image

from engine.adapters.contracts import DetectionRequest, InferenceRequest
from engine.blocks.reading import NativeVisionReading, read_native
from engine.models import detect
from engine.models.manager import ModelUnavailable
from spec.inference import DetectionObservation, TextObservation


def execute_legacy(image: Image.Image, request: InferenceRequest) -> tuple[list[DetectionObservation], list[TextObservation]]:
    if isinstance(request, DetectionRequest):
        detections = detect(image, request.model_id, request.classes, request.min_conf)
        return [DetectionObservation(label=d.label, confidence=d.confidence, box=tuple(d.box))  # type: ignore[arg-type]
                for d in detections], []
    if request.model_id != "apple-vision":
        raise ModelUnavailable(f"No implemented reader adapter for {request.model_id!r}; no fallback was selected")
    reading = read_native(image)
    if isinstance(reading, NativeVisionReading):
        return [], [row for row in reading.readings if row.kind == request.task]
    strings = reading.texts if request.task == "ocr" else reading.barcodes
    return [], [TextObservation(text=value, kind=request.task) for value in strings]
