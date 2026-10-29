"""Deterministic colored-rectangle test detector, not a learned warehouse model."""
from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image

from spec.models import Detection

PALETTE = {"pallet": (36, 166, 112), "damaged pallet": (231, 94, 67),
           "damaged carton": (224, 163, 48), "carton": (88, 137, 209)}


def detect_fixture(image: Image.Image, classes: list[str], min_conf: float) -> list[Detection]:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    height, width = pixels.shape[:2]
    detections: list[Detection] = []
    if min_conf > 0.99:
        return detections
    for label in classes:
        color = PALETTE.get(label)
        if color is None:
            raise ValueError(f"Synthetic fixture detector supports only {', '.join(PALETTE)}")
        mask = np.max(np.abs(pixels - np.array(color)), axis=2) <= 5
        visited = np.zeros(mask.shape, dtype=bool)
        for y, x in zip(*np.where(mask), strict=True):
            if visited[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(int(y), int(x))])
            visited[y, x] = True
            x0 = x1 = int(x)
            y0 = y1 = int(y)
            area = 0
            while queue:
                cy, cx = queue.popleft()
                area += 1
                x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            if area >= 16:
                detections.append(Detection(label=label, confidence=0.99,
                    box=[x0 / width, y0 / height, (x1 + 1) / width, (y1 + 1) / height]))
    return sorted(detections, key=lambda d: (d.box[0], d.box[1], d.label))
