"""Bounded, identity-bound facade over the coded local adapter registry."""
from __future__ import annotations

import hashlib
import math
import struct
import threading
import time

from PIL import Image

from engine.adapters.contracts import InferenceRequest
from engine.adapters.identity import resolve_execution_identity
from engine.adapters.legacy import execute_legacy
from spec.inference import InferenceResult, InferenceTiming


class InferenceAborted(ValueError):
    """No evidence or events may be committed from this request."""


def _check_active(deadline: float | None, cancelled: threading.Event | None) -> None:
    if cancelled is not None and cancelled.is_set():
        raise InferenceAborted("Inference was cancelled; results were discarded")
    if deadline is not None and time.monotonic() >= deadline:
        raise InferenceAborted("Inference deadline expired; results were discarded")


def run_inference(image: Image.Image, request: InferenceRequest, *,
                  expected_identity_hash: str | None = None,
                  deadline_monotonic_s: float | None = None,
                  cancelled: threading.Event | None = None) -> InferenceResult:
    started = time.perf_counter()
    if deadline_monotonic_s is not None and not math.isfinite(deadline_monotonic_s):
        raise ValueError("Inference deadline must be finite")
    _check_active(deadline_monotonic_s, cancelled)
    if min(image.size) <= 0 or max(image.size) > 32768 or image.width * image.height > 40_000_000:
        raise ValueError("Adapter image must contain between 1 and 40 million pixels")
    identity = resolve_execution_identity(request)
    if expected_identity_hash is not None and identity.identity_hash != expected_identity_hash:
        raise InferenceAborted("Adapter identity changed after compilation; rebuild and evaluate")
    if identity.unavailable_artifacts:
        raise InferenceAborted("Adapter cannot execute; missing local artifacts: " + ", ".join(identity.unavailable_artifacts))
    # Own pixels for the entire call; a concurrent producer cannot change evidence.
    pixels = image.convert("RGB").copy()
    pixel_hash = hashlib.sha256(b"RGB\0" + struct.pack(">II", pixels.width, pixels.height) + pixels.tobytes()).hexdigest()
    _check_active(deadline_monotonic_s, cancelled)
    detections, readings = execute_legacy(pixels, request)
    _check_active(deadline_monotonic_s, cancelled)
    if resolve_execution_identity(request).identity_hash != identity.identity_hash:
        raise InferenceAborted("Adapter identity changed while running; results were discarded")
    _check_active(deadline_monotonic_s, cancelled)
    return InferenceResult(task=request.task, input_size=pixels.size, input_pixels_sha256=pixel_hash,
        detections=detections, readings=readings, identity=identity,
        timing=InferenceTiming(total_ms=(time.perf_counter() - started) * 1000),
        warnings=["Synthetic color fixture; not a warehouse detector."] if request.model_id == "fixture-color-v1" else [])
