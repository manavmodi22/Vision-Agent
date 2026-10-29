"""Image-only PP-OCR processing adapted from pinned Apache-2.0 PaddleX.

Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.
Licensed under the Apache License, Version 2.0. See upstream/LICENSE and NOTICE.
Changes: standalone functions, strict finite/size guards, scores retained with sort.
No Shapely, PaddleX, language correction, orientation model, or network dependency.
"""

import math

import cv2
import numpy as np
import pyclipper


def detection_input(image):
    h, w = image.shape[:2]
    if h < 1 or w < 1 or max(h, w) > 8192 or h * w > 24_000_000:
        raise ValueError("Image exceeds prototype bounds")
    if h + w < 64:
        padded = np.zeros((max(32, h), max(32, w), 3), np.uint8)
        padded[:h, :w] = image
        image = padded
    ph, pw = image.shape[:2]
    ratio = min(1.0, 960 / max(ph, pw))
    rh = max(int(round(int(ph * ratio) / 32) * 32), 32)
    rw = max(int(round(int(pw * ratio) / 32) * 32), 32)
    resized = image if (rh, rw) == (ph, pw) else cv2.resize(image, (rw, rh))
    channels = list(cv2.split(resized))
    for i, (mean, std) in enumerate(zip((0.485, 0.456, 0.406), (0.229, 0.224, 0.225), strict=True)):
        channels[i] = channels[i].astype(np.float32)
        channels[i] *= (1 / 255) / std
        channels[i] += -mean / std
    return cv2.merge(channels).transpose(2, 0, 1)[None].copy()


def mini_box(contour):
    rectangle = cv2.minAreaRect(contour)
    points = sorted(cv2.boxPoints(rectangle), key=lambda p: p[0])
    a, d = (0, 1) if points[1][1] > points[0][1] else (1, 0)
    b, c = (2, 3) if points[3][1] > points[2][1] else (3, 2)
    return np.array([points[a], points[b], points[c], points[d]]), min(rectangle[1])


def box_score(bitmap, points):
    h, w = bitmap.shape
    box = points.copy()
    x0 = max(0, min(math.floor(box[:, 0].min()), w - 1))
    x1 = max(0, min(math.ceil(box[:, 0].max()), w - 1))
    y0 = max(0, min(math.floor(box[:, 1].min()), h - 1))
    y1 = max(0, min(math.ceil(box[:, 1].max()), h - 1))
    mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
    box -= [x0, y0]
    cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
    return cv2.mean(bitmap[y0 : y1 + 1, x0 : x1 + 1], mask)[0]


def detection_boxes(prediction, height, width):
    if prediction.ndim != 4 or prediction.shape[:2] != (1, 1):
        raise ValueError(f"Unexpected detector output {prediction.shape}")
    bitmap = prediction[0, 0]
    if not np.isfinite(bitmap).all() or bitmap.min() < 0 or bitmap.max() > 1:
        raise ValueError("Invalid detector scores")
    contours, _ = cv2.findContours(
        ((bitmap > 0.3) * 255).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    result = []
    for contour in contours[:1000]:
        points, small = mini_box(contour)
        if small < 3:
            continue
        score = box_score(bitmap, points)
        if score < 0.6:
            continue
        distance = cv2.contourArea(points) * 1.5 / cv2.arcLength(points, True)
        offset = pyclipper.PyclipperOffset()
        offset.AddPath(points, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        expanded = offset.Execute(distance)
        if len(expanded) != 1:
            raise ValueError("Unexpected non-single expanded convex rectangle")
        box, small = mini_box(np.array(expanded).reshape(-1, 1, 2))
        if small < 5:
            continue
        for point in box:
            point[0] = max(0, min(round(point[0] * width / bitmap.shape[1]), width))
            point[1] = max(0, min(round(point[1] * height / bitmap.shape[0]), height))
        result.append((box.astype(np.int16), score))
    result.sort(key=lambda row: (row[0][0][1], row[0][0][0]))
    for i in range(len(result) - 1):
        for j in range(i, -1, -1):
            a, b = result[j][0][0], result[j + 1][0][0]
            if abs(b[1] - a[1]) < 10 and b[0] < a[0]:
                result[j], result[j + 1] = result[j + 1], result[j]
            else:
                break
    if len(result) > 128:
        raise ValueError("Prototype text-region limit exceeded")
    return result


def crop_quad(image, quad):
    points, _ = mini_box(quad.astype(np.int32))
    width = int(max(np.linalg.norm(points[0] - points[1]), np.linalg.norm(points[2] - points[3])))
    height = int(max(np.linalg.norm(points[0] - points[3]), np.linalg.norm(points[1] - points[2])))
    if width < 1 or height < 1:
        raise ValueError("Degenerate text crop")
    target = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    transform = cv2.getPerspectiveTransform(points, target)
    crop = cv2.warpPerspective(
        image, transform, (width, height), borderMode=cv2.BORDER_REPLICATE, flags=cv2.INTER_CUBIC
    )
    return np.rot90(crop) if height / width >= 1.5 else crop


def recognition_input(image):
    h, w = image.shape[:2]
    padded_width = int(48 * max(320 / 48, w / h))
    if padded_width > 3200:
        padded_width = resized_width = 3200
    else:
        resized_width = min(padded_width, math.ceil(48 * w / h))
    resized = cv2.resize(image, (resized_width, 48)).astype(np.float32)
    normalized = resized.transpose(2, 0, 1) / 255
    normalized -= 0.5
    normalized /= 0.5
    output = np.zeros((3, 48, padded_width), np.float32)
    output[:, :, :resized_width] = normalized
    return output[None]


def decode_ctc(prediction, characters):
    if prediction.ndim != 3 or prediction.shape[0] != 1 or prediction.shape[2] != len(characters):
        raise ValueError(f"Unexpected recognizer output {prediction.shape}")
    if not np.isfinite(prediction).all() or prediction.min() < 0 or prediction.max() > 1:
        raise ValueError("Invalid recognition scores")
    indices = prediction[0].argmax(axis=-1)
    probabilities = prediction[0].max(axis=-1)
    selected = np.ones(len(indices), dtype=bool)
    selected[1:] = indices[1:] != indices[:-1]
    selected &= indices != 0
    text = "".join(characters[index] for index in indices[selected])
    confidence = float(probabilities[selected].mean()) if selected.any() else 0.0
    return text, confidence
