"""Isolated PP-OCRv5 CPU prototype; never downloads models or imports PaddleX."""

import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
from image_ops import crop_quad, decode_ctc, detection_boxes, detection_input, recognition_input
from paddle.inference import Config, create_predictor
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
MODEL_ROOT = ROOT / ".visionapp/adapter-probes/ocr/models"
PINNED_FILES = {
    "PP-OCRv5_mobile_det": {
        "config.json": "7ac1c33f377ba58561f4b89d3180b6add2b7c5c60a4edac90fa4e0ceccdc6665",
        "inference.json": "05feef1acb00aa4cd7362b15f7f501fc4f99d7b1fa73c1c871e0c7b1504b0f5c",
        "inference.pdiparams": "afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b",
    },
    "en_PP-OCRv5_mobile_rec": {
        "config.json": "16103ac291a82fca50f0bb000d62a4b8168f6042f03c89c44cf32f241d1eb1f2",
        "inference.json": "fd1b6ec722ea841a72d3ba43e527df1d1066d5d7808e0503ee3eec7265188753",
        "inference.pdiparams": "3ec8a97ed6cefe8568d3e2ee90bb193299b566a7661aa4fd52d224b96b59f66b",
    },
}


def verify_files(model_root):
    for model, files in PINNED_FILES.items():
        for name, digest in files.items():
            path = model_root / model / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Pinned local artifact mismatch: {model}/{name}")


def predictor(directory):
    config = Config(str(directory / "inference.json"), str(directory / "inference.pdiparams"))
    config.disable_gpu()
    config.disable_mkldnn()
    config.set_cpu_math_library_num_threads(2)
    config.enable_new_ir()
    config.enable_new_executor()
    config.set_optimization_level(3)
    config.enable_memory_optim()
    config.disable_glog_info()
    return create_predictor(config)


def infer(model, data):
    inputs, outputs = model.get_input_names(), model.get_output_names()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError("Only the pinned one-input/one-output models are supported")
    handle = model.get_input_handle(inputs[0])
    handle.reshape(data.shape)
    handle.copy_from_cpu(data)
    model.run()
    return model.get_output_handle(outputs[0]).copy_to_cpu()


class DirectOCR:
    def __init__(self, model_root=MODEL_ROOT):
        verify_files(model_root)
        cv2.setNumThreads(2)
        self.detector = predictor(model_root / "PP-OCRv5_mobile_det")
        self.recognizer = predictor(model_root / "en_PP-OCRv5_mobile_rec")
        config = json.loads((model_root / "en_PP-OCRv5_mobile_rec/config.json").read_text())
        self.characters = ["blank", *config["PostProcess"]["character_dict"], " "]

    def read(self, image_path):
        start = time.perf_counter()
        with Image.open(image_path) as image:
            width, height = image.size
            if max(width, height) > 8192 or width * height > 24_000_000:
                raise ValueError("Image exceeds prototype bounds")
            image.load()
            rgb = np.asarray(image.convert("RGB"))
        bgr = rgb[:, :, ::-1].copy()
        t0 = time.perf_counter()
        prediction = infer(self.detector, detection_input(bgr))
        boxes = detection_boxes(prediction, bgr.shape[0], bgr.shape[1])
        detection_ms = (time.perf_counter() - t0) * 1000
        observations = []
        for polygon, score in boxes:
            t1 = time.perf_counter()
            crop = crop_quad(bgr, polygon)
            result = infer(self.recognizer, recognition_input(crop))
            text, confidence = decode_ctc(result, self.characters)
            observations.append(
                {
                    "text": text,
                    "recognition_score": confidence,
                    "detection_score": float(score),
                    "polygon_pixels": polygon.tolist(),
                    "recognition_ms": (time.perf_counter() - t1) * 1000,
                }
            )
        return {
            "image_size": [bgr.shape[1], bgr.shape[0]],
            "observations": observations,
            "detection_ms": detection_ms,
            "total_ms": (time.perf_counter() - start) * 1000,
        }
