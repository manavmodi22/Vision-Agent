"""Pinned YOLOX-s ONNX CPU inference; no download, remapping or fallback."""
from __future__ import annotations

import hashlib
import math
import threading
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

import numpy as np
from PIL import Image

from engine.models.artifacts import assert_model_fingerprint, model_content_fingerprint
from engine.models.manager import ModelUnavailable, model_directory
from engine.models.yolox_config import (
    COCO_CLASSES,
    INTER_OP_THREADS,
    INTRA_OP_THREADS,
    MODEL_BYTES,
    MODEL_FILENAME,
    MODEL_ID,
    MODEL_SHA256,
)
from engine.models.yolox_ops import FloatArray, postprocess, preprocess
from spec.models import Detection

_LOAD_LOCK = threading.Lock()


class _Session(Protocol):
    def run(self, output_names: list[str] | None, input_feed: dict[str, FloatArray]) -> list[object]: ...


@lru_cache(maxsize=1)
def _load(path_string: str, fingerprint: str) -> tuple[_Session, str]:
    assert_model_fingerprint(MODEL_ID, fingerprint)
    try:
        import onnxruntime as ort

        path = Path(path_string)
        if path.stat().st_size != MODEL_BYTES:
            raise ModelUnavailable("YOLOX checkpoint size does not match the pinned official release")
        model_bytes = path.read_bytes()
        if len(model_bytes) != MODEL_BYTES or hashlib.sha256(model_bytes).hexdigest() != MODEL_SHA256:
            raise ModelUnavailable("YOLOX checkpoint SHA256 does not match the pinned official release")
        if "CPUExecutionProvider" not in ort.get_available_providers():
            raise ModelUnavailable("ONNX Runtime CPUExecutionProvider is unavailable")
        options = ort.SessionOptions()
        options.intra_op_num_threads = INTRA_OP_THREADS
        options.inter_op_num_threads = INTER_OP_THREADS
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # Pass verified bytes, not a mutable path: ORT cannot load a raced replacement.
        session = ort.InferenceSession(model_bytes, sess_options=options,
                                       providers=["CPUExecutionProvider"])
        session.disable_fallback()
        if session.get_providers() != ["CPUExecutionProvider"]:
            raise ModelUnavailable("YOLOX requires CPUExecutionProvider exclusively")
        inputs, outputs = session.get_inputs(), session.get_outputs()
        if (len(inputs) != 1 or inputs[0].shape != [1, 3, 640, 640]
                or inputs[0].type != "tensor(float)" or len(outputs) != 1
                or outputs[0].shape != [1, 8400, 85] or outputs[0].type != "tensor(float)"):
            raise ModelUnavailable("YOLOX ONNX input/output contract does not match the pinned adapter")
        assert_model_fingerprint(MODEL_ID, fingerprint)
        return cast(_Session, session), str(inputs[0].name)
    except ModelUnavailable:
        raise
    except Exception as exc:
        raise ModelUnavailable(f"Failed to load local YOLOX ONNX CPU model: {exc}") from exc


def detect_yolox(image: Image.Image, classes: list[str], min_conf: float) -> list[Detection]:
    unknown = set(classes) - set(COCO_CLASSES)
    if unknown or not classes:
        raise ModelUnavailable("YOLOX-s supports exact COCO class names only; unsupported: "
                               + (", ".join(sorted(unknown)) or "empty class list")
                               + ". No class remapping or fallback is available.")
    if not math.isfinite(min_conf) or not 0 <= min_conf <= 1:
        raise ModelUnavailable("YOLOX confidence threshold must be finite and between 0 and 1")
    tensor, ratio = preprocess(image)
    fingerprint = model_content_fingerprint(MODEL_ID)
    with _LOAD_LOCK:
        session, input_name = _load(str(model_directory() / MODEL_ID / MODEL_FILENAME), fingerprint)
    try:
        outputs = session.run(None, {input_name: tensor})
    except Exception as exc:
        raise ModelUnavailable(f"YOLOX CPU inference failed; no fallback was used: {exc}") from exc
    if len(outputs) != 1 or not isinstance(outputs[0], np.ndarray):
        raise ModelUnavailable("YOLOX returned an invalid ONNX output collection")
    detections = postprocess(outputs[0], image.size, ratio, classes, min_conf)
    assert_model_fingerprint(MODEL_ID, fingerprint)
    return detections
