"""Project existing block parameters into typed adapter requests."""
from __future__ import annotations

from engine.adapters.contracts import BarcodeRequest, DetectionRequest, InferenceRequest, OcrRequest
from engine.blocks.params import DetectParams, ReadingParams
from spec.models import BlockSpec


def request_for_block(block: BlockSpec) -> InferenceRequest | None:
    if block.type in {"detect", "detect_open_vocab"}:
        params = DetectParams.model_validate(block.params)
        return DetectionRequest(model_id=params.model, classes=params.classes, min_conf=params.min_conf)
    if block.type == "ocr":
        return OcrRequest(languages=ReadingParams.model_validate(block.params).languages)
    if block.type == "barcode":
        return BarcodeRequest()
    return None
