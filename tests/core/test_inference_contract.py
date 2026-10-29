"""Adapter evidence must not fabricate geometry, identity or measurements."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from engine.adapters.contracts import BarcodeRequest, DetectionRequest, OcrRequest
from spec.inference import DetectionObservation, Geometry, InferenceTiming, TextObservation


def test_unknown_native_evidence_stays_null_and_text_is_literal() -> None:
    reading = TextObservation(text="\u0425ABC-009Y", kind="ocr")
    assert reading.confidence is None and reading.box is None and reading.polygon is None
    assert reading.text != "XABC-009Y"
    timing = InferenceTiming(total_ms=12)
    assert timing.inference_ms is None and timing.model_cached is None


@pytest.mark.parametrize("box", [(0.2, 0.1, 0.2, 0.9), (-0.1, 0, 1, 1), (0, 0, float("nan"), 1)])
def test_invalid_observation_geometry_is_rejected(box: tuple[float, ...]) -> None:
    with pytest.raises(ValidationError):
        DetectionObservation.model_validate({"label": "person", "confidence": 0.8, "box": box})


def test_polygon_coordinates_have_a_consistent_envelope() -> None:
    polygon = [(0.1, 0.2), (0.7, 0.2), (0.4, 0.8)]
    assert Geometry(polygon=polygon).box == (0.1, 0.2, 0.7, 0.8)
    with pytest.raises(ValidationError, match="envelope"):
        Geometry(polygon=polygon, box=(0, 0, 1, 1))
    with pytest.raises(ValidationError, match="positive area"):
        Geometry(polygon=[(0, 0), (0.1, 0.1), (0.2, 0.2)])


def test_requests_reject_unsupported_readers_and_options() -> None:
    with pytest.raises(ValidationError):
        OcrRequest.model_validate({"model_id": "paddleocr"})
    with pytest.raises(ValidationError, match="en-US"):
        OcrRequest(languages=["auto"])
    with pytest.raises(ValidationError):
        BarcodeRequest.model_validate({"expected": "001234"})
    with pytest.raises(ValidationError):
        DetectionRequest(model_id="fixture-color-v1", classes=["pallet"], min_conf=float("inf"))


def test_unmeasured_time_cannot_be_fabricated_from_nonfinite_values() -> None:
    with pytest.raises(ValidationError):
        InferenceTiming(total_ms=float("nan"))
