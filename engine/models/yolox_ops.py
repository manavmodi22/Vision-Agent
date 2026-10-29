"""YOLOX preprocessing/decode/NMS adapted from the pinned Apache-2.0 source.

Copyright (c) Megvii Inc. All rights reserved.
See licenses/YOLOX-NOTICE.md for upstream files, modifications and license.
"""
from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from engine.models.manager import ModelUnavailable
from engine.models.yolox_config import COCO_CLASSES, INPUT_SIZE, NMS_IOU
from spec.models import Detection

FloatArray = NDArray[np.float32]


def preprocess(image: Image.Image) -> tuple[FloatArray, float]:
    if min(image.size) <= 0 or max(image.size) > 32768 or image.width * image.height > 40_000_000:
        raise ModelUnavailable("YOLOX image must contain between 1 and 40 million pixels")
    # Official input is raw BGR, not RGB or normalized 0..1; padding is top-left.
    bgr = np.asarray(image.convert("RGB"), dtype=np.uint8)[..., ::-1]
    ratio = min(INPUT_SIZE / image.height, INPUT_SIZE / image.width)
    width, height = int(image.width * ratio), int(image.height * ratio)
    if min(width, height) < 1:
        raise ModelUnavailable("YOLOX image aspect ratio produces an empty resized dimension")
    padded = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
    padded[:height, :width] = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None], ratio


def _nms(boxes: FloatArray, scores: FloatArray) -> list[int]:
    # Preserve upstream inclusive +1 pixel areas, score ordering and IoU comparison.
    x1, y1, x2, y2 = (boxes[:, i] for i in range(4))
    with np.errstate(over="ignore", invalid="ignore"):
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    if not np.isfinite(areas).all():
        raise ModelUnavailable("YOLOX decoded geometry exceeds finite NMS area bounds")
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        index = int(order[0])
        keep.append(index)
        xx1, yy1 = np.maximum(x1[index], x1[order[1:]]), np.maximum(y1[index], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[index], x2[order[1:]]), np.minimum(y2[index], y2[order[1:]])
        intersection = np.maximum(0.0, xx2 - xx1 + 1) * np.maximum(0.0, yy2 - yy1 + 1)
        overlap = intersection / (areas[index] + areas[order[1:]] - intersection)
        order = order[np.where(overlap <= NMS_IOU)[0] + 1]
    return keep


def postprocess(output: FloatArray, size: tuple[int, int], ratio: float,
                classes: list[str], min_conf: float) -> list[Detection]:
    if output.dtype != np.float32 or output.shape != (1, 8400, 85) or not np.isfinite(output).all():
        raise ModelUnavailable("YOLOX returned an invalid float32 [1,8400,85] tensor")
    if np.any(output[..., 4:] < 0) or np.any(output[..., 4:] > 1):
        raise ModelUnavailable("YOLOX returned scores outside [0,1]")
    # Decode a copy: ORT's raw output and callers' evidence remain unchanged.
    prediction = output.copy()
    grids, expanded = [], []
    for stride in (8, 16, 32):
        xv, yv = np.meshgrid(np.arange(INPUT_SIZE // stride), np.arange(INPUT_SIZE // stride))
        grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(grid)
        expanded.append(np.full((*grid.shape[:2], 1), stride))
    grid_array, strides = np.concatenate(grids, 1), np.concatenate(expanded, 1)
    with np.errstate(over="ignore", invalid="ignore"):
        prediction[..., :2] = (prediction[..., :2] + grid_array) * strides
        prediction[..., 2:4] = np.exp(prediction[..., 2:4]) * strides
        pred = prediction[0]
        boxes = np.concatenate((pred[:, :2] - pred[:, 2:4] / 2,
                                pred[:, :2] + pred[:, 2:4] / 2), axis=1) / ratio
    if not np.isfinite(boxes).all():
        raise ModelUnavailable("YOLOX returned non-finite decoded geometry")
    scores = pred[:, 4:5] * pred[:, 5:]
    labels = scores.argmax(1)
    best_scores = scores[np.arange(len(labels)), labels]
    valid = best_scores > min_conf  # Upstream uses strict >, not >=.
    boxes, best_scores, labels = boxes[valid], best_scores[valid], labels[valid]
    detections: list[Detection] = []
    # NMS runs across ALL COCO classes before requested-class filtering.
    for index in _nms(boxes, best_scores):
        name = COCO_CLASSES[int(labels[index])]
        if name not in classes:
            continue
        values = np.clip(boxes[index] / np.array([size[0], size[1], size[0], size[1]]), 0, 1)
        box = [float(value) for value in values]
        if box[0] < box[2] and box[1] < box[3]:
            detections.append(Detection(label=name, confidence=float(best_scores[index]), box=box))
    return detections
