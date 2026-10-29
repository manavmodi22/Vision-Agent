"""Copy user-selected media into project ownership; never mutate source files."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from engine.models.artifacts import content_hash

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


def import_paths(paths: list[str], destination: Path, limit: int = 50) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    selected: list[Path] = []
    for raw in paths:
        source = Path(raw).expanduser().resolve(strict=True)
        if source.is_dir():
            selected.extend(sorted(p for p in source.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS))
        elif source.is_file():
            selected.append(source)
    if not selected:
        raise ValueError("No supported image or recorded video selected")
    created: list[str] = []
    imported_sources: dict[str, dict[str, str]] = {}
    try:
        for source in selected:
            if len(created) >= limit:
                break
            if source.suffix.lower() in IMAGE_EXTENSIONS:
                target = destination / f"{uuid.uuid4().hex[:8]}-{source.stem[:60]}.png"
                with Image.open(source) as image:
                    image.load()
                    source_orientation = str(image.getexif().get(274, 1))
                    if image.width * image.height > 40_000_000:
                        raise ValueError("Images must be at most 40 megapixels")
                    ImageOps.exif_transpose(image).convert("RGB").save(target)
                created.append(str(target))
                imported_sources[target.name] = {"source_name": source.name, "source_path": str(source),
                    "source_orientation": source_orientation, "source_sha256": content_hash(source),
                    "source_kind": "image", "data_origin": "unknown", "exposure_tracking_version": "1"}
            elif source.suffix.lower() in VIDEO_EXTENSIONS:
                created.extend(sample_video(source, destination, limit - len(created), provenance=imported_sources))
            else:
                raise ValueError(f"Unsupported media format: {source.suffix}")
        if imported_sources:
            provenance_path = destination / "media-sources.json"
            provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
            if not isinstance(provenance, dict):
                raise ValueError("Media import provenance is invalid")
            provenance.update(imported_sources)
            temporary = provenance_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(provenance, indent=2))
            temporary.replace(provenance_path)
    except (OSError, ValueError):
        for name in created:
            Path(name).unlink(missing_ok=True)
        raise
    if not created:
        raise ValueError("The selected media contained no decodable frames")
    return created


def sample_video(path: Path, destination: Path, limit: int, *,
                 provenance: dict[str, dict[str, str]] | None = None) -> list[str]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"Cannot decode video: {path.name}")
    paths: list[str] = []
    source_hash = content_hash(path)
    try:
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if count <= 0:
            raise ValueError("Video must have a finite frame count")
        step = max(1, count // limit)
        prefix = uuid.uuid4().hex[:8]
        for index in range(0, count, step):
            if len(paths) >= limit:
                break
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"Could not read video frame {index}")
            output = destination / f"{prefix}-frame-{index:06d}.png"
            if not cv2.imwrite(str(output), frame):
                raise ValueError("Could not save sampled video frame")
            paths.append(str(output))
            if provenance is not None:
                record = {"source_name": path.name, "source_path": str(path), "source_sha256": source_hash,
                          "source_kind": "recorded_video", "frame_index": str(index), "data_origin": "unknown",
                          "exposure_tracking_version": "1"}
                timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
                if math.isfinite(timestamp) and timestamp >= 0 and (index == 0 or timestamp > 0):
                    record["timestamp_s"] = str(timestamp)
                provenance[output.name] = record
    except (ValueError, cv2.error):
        for filename in paths:
            Path(filename).unlink(missing_ok=True)
        raise
    finally:
        capture.release()
    return paths


def media_fingerprint(paths: list[str]) -> str:
    digest = hashlib.sha256()
    for raw in sorted(paths):
        path = Path(raw)
        digest.update(path.name.encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
