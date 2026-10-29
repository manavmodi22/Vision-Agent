"""Strict native reader protocol, preserving actual observations and provenance."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from engine.adapters import legacy
from engine.adapters.contracts import BarcodeRequest, OcrRequest
from engine.blocks import reading
from engine.blocks.reading import NativeVisionReading, VisionReading


def payload() -> dict[str, object]:
    quad = [[.1, .2], [.8, .25], [.75, .6], [.15, .55]]
    row = {"text": "\u0425ABC-990Y", "kind": "ocr", "box": [.1, .2, .8, .6],
           "polygon": quad, "confidence": .75, "symbology": None}
    return {"schema_version": 2, "request_policy": "apple-vision-en-us-v2",
            "coordinate_space": "normalized_top_left", "input_size": [200, 100],
            "texts": ["\u0425ABC-990Y", "\u0425ABC-990Y"], "barcodes": ["001234"],
            "readings": [row, copy.deepcopy(row), {"text": "001234", "kind": "barcode", "box": None,
                         "polygon": None, "confidence": None, "symbology": "VNBarcodeSymbologyQR"}],
            "warnings": ["Barcode geometry unavailable"]}


def test_native_observations_keep_duplicates_raw_text_geometry_and_nulls(monkeypatch: pytest.MonkeyPatch) -> None:
    decoded = NativeVisionReading.model_validate(payload())
    monkeypatch.setattr(legacy, "read_native", lambda image: decoded)
    detections, observations = legacy.execute_legacy(Image.new("RGB", (200, 100)), OcrRequest())
    assert not detections
    assert len(observations) == 2 and observations[0] == observations[1]
    assert observations[0].text.startswith("\u0425")
    assert observations[0].box == (.1, .2, .8, .6)
    assert observations[0].polygon == [(.1, .2), (.8, .25), (.75, .6), (.15, .55)]
    assert observations[0].confidence == .75
    _, barcodes = legacy.execute_legacy(Image.new("RGB", (200, 100)), BarcodeRequest())
    assert len(barcodes) == 1 and barcodes[0].text == "001234"
    assert barcodes[0].confidence is None and barcodes[0].box is None
    assert barcodes[0].symbology == "VNBarcodeSymbologyQR"


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("request_policy", "unknown"),
    ("coordinate_space", "bottom_left"), ("texts", ["XABC-990Y"]),
    ("barcodes", []), ("input_size", [0, 100]),
])
def test_wrong_protocol_and_inconsistent_projections_reject(field: str, value: object) -> None:
    record = payload()
    record[field] = value
    with pytest.raises(ValidationError):
        NativeVisionReading.model_validate(record)


@pytest.mark.parametrize("geometry", [
    {"box": [.8, .2, .1, .6]}, {"polygon": [[.1, .2], [1.1, .2], [.5, .6]]},
    {"confidence": float("nan")}, {"box": [.2, .2, .8, .6]},
])
def test_bad_native_geometry_is_not_clamped_or_repaired(geometry: dict[str, object]) -> None:
    record = payload()
    record["readings"][0].update(geometry)  # type: ignore[index]
    with pytest.raises(ValidationError):
        NativeVisionReading.model_validate(record)


def test_bridge_explicitly_requests_v2_and_rejects_dimension_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "VisionApp"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("VISION_APP_BINARY", str(binary))
    calls = []
    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        transported = Image.open(args[2])
        assert transported.size == (200, 100)
        assert not transported.getexif()
        return subprocess.CompletedProcess(args, 0, json.dumps(payload()), "")
    monkeypatch.setattr(reading.subprocess, "run", run)
    source = Image.new("RGB", (200, 100))
    exif = Image.Exif()
    exif[274] = 6
    source.info["exif"] = exif.tobytes()
    assert reading.read_native(source).input_size == (200, 100)
    assert calls[0][1:] == ["--analyze-image", calls[0][2], "--protocol", "2"]
    monkeypatch.setattr(reading.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(payload()), ""))
    with pytest.raises(ValueError, match="dimensions"):
        reading.read_native(Image.new("RGB", (201, 100)))


def test_legacy_evidence_remains_readable_but_old_bridge_never_silently_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = {"texts": ["ABC"], "barcodes": []}
    assert VisionReading.model_validate(record).texts == ["ABC"]
    binary = tmp_path / "old-bridge"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("VISION_APP_BINARY", str(binary))
    monkeypatch.setattr(reading.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(record), ""))
    with pytest.raises(ValidationError):
        reading.read_native(Image.new("RGB", (200, 100)))
