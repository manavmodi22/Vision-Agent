"""Bounded media enumeration; video frames retain source timestamps."""
from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Iterator
from pathlib import Path

from PIL import Image

from spec.models import SourceSpec

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def source_frames(source: SourceSpec, root: Path, fps: float, max_frames: int) -> Iterator[tuple[Path, float]]:
    path = (root / source.path).resolve()
    if source.type == "image_file":
        if not path.is_file():
            raise ValueError(f"Image does not exist: {source.path}")
        yield path, 0
    elif source.type == "image_folder":
        if not path.is_dir():
            raise ValueError(f"Image folder does not exist: {source.path}")
        images = sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
        if not images:
            raise ValueError("No supported images found. Import PNG, JPEG, BMP, TIFF or WebP samples.")
        for image in images[:max_frames]:
            # Independent sample order supplies no elapsed-time evidence.
            yield image, 0.0
    elif source.type == "video_file":
        yield from video_frames(path, root, fps, max_frames)
    else:
        raise ValueError(f"Source '{source.type}' is unavailable; import a recording")


def video_frames(path: Path, root: Path, sample_fps: float, max_frames: int) -> Iterator[tuple[Path, float]]:
    if importlib.util.find_spec("cv2") is None:
        raise ValueError("Video decoding requires opencv-python-headless")
    import cv2

    if not path.is_file():
        raise ValueError(f"Video does not exist: {path}")
    token = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode()).hexdigest()[:16]
    output = root / "frames" / token
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot decode video: {path.name}")
        native_fps = capture.get(cv2.CAP_PROP_FPS)
        if native_fps <= 0:
            raise ValueError("Video does not expose a valid frame rate")
        next_sample = 0.0
        index = emitted = 0
        while emitted < max_frames:
            ok, pixels = capture.read()
            if not ok:
                break
            timestamp = index / native_fps
            index += 1
            if timestamp + 1e-8 < next_sample:
                continue
            frame_path = output / f"frame-{emitted:06d}.png"
            Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)).save(frame_path)
            yield frame_path, timestamp
            emitted += 1
            next_sample += 1 / min(sample_fps, native_fps)
        if emitted == 0:
            raise ValueError("No decodable video frames found")
    finally:
        capture.release()
