"""Content and source provenance shared by import, evaluation and training."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps

from engine.models.artifacts import content_hash


def pixel_hash(path: Path) -> str:
    with Image.open(path) as image:
        return pixel_hash_image(image)


def pixel_hash_image(image: Image.Image) -> str:
    """Same identity for ephemeral frames and later imported image pixels."""
    pixels = ImageOps.exif_transpose(image).convert("RGB")
    digest = hashlib.sha256(str(pixels.size).encode())
    digest.update(pixels.tobytes())
    return digest.hexdigest()


def relative_image(root: Path, image_path: str) -> str:
    path = (root / image_path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Evaluation image must be inside this project")
    return path.relative_to(root.resolve()).as_posix()


def source_record(root: Path, image_path: str) -> dict[str, str]:
    relative = relative_image(root, image_path)
    image = (root / image_path).resolve()
    manifest = image.parent / "media-sources.json"
    record: dict[str, str] = {}
    if manifest.is_file():
        raw = json.loads(manifest.read_text())
        if not isinstance(raw, dict) or not isinstance(raw.get(image.name, {}), dict):
            raise ValueError("Media source provenance is invalid")
        record = {str(key): str(value) for key, value in raw.get(image.name, {}).items()}
    # Public sample frames are copied as PNGs after extraction. Their independence
    # identity remains the original recording, not each intermediate PNG file.
    return {**record, **_public_sample_record(root, relative)}


def _public_sample_record(root: Path, relative: str) -> dict[str, str]:
    provenance = root / "sample-source.json"
    if not provenance.is_file():
        return {}
    sample = json.loads(provenance.read_text())
    if not isinstance(sample, dict):
        raise ValueError("Public sample provenance is invalid")
    if sample.get("sample_id") != "nvidia-warehouse-real":
        return {}
    frames = sample.get("frames")
    if frames is None:
        # Before explicit frame mappings shipped, import_sample only accepted an
        # empty project and appended its frames in source_timestamps_s order.
        # Later media imports append to project.media; they are not sample frames.
        project_path = root / "project.json"
        if not project_path.is_file():
            return {}
        project = json.loads(project_path.read_text())
        count, timestamps = sample.get("frame_count"), sample.get("source_timestamps_s")
        media = project.get("media", []) if isinstance(project, dict) else []
        if (not isinstance(count, int) or isinstance(count, bool) or count <= 0
                or not isinstance(timestamps, list) or len(timestamps) != count
                or not isinstance(media, list) or len(media) < count):
            raise ValueError("Legacy public sample frame mapping is incomplete")
        frames = [{"image_path": path, "timestamp_s": timestamp}
                  for path, timestamp in zip(media[:count], timestamps, strict=True)]
    if not isinstance(frames, list) or any(not isinstance(frame, dict) for frame in frames):
        raise ValueError("Public sample frame mapping is invalid")
    matching = [frame for frame in frames
                if isinstance(frame.get("image_path"), str)
                and relative_image(root, frame["image_path"]) == relative]
    if not matching:
        return {}
    if len(matching) != 1:
        raise ValueError("Public sample frame mapping contains duplicates")
    digest, video = sample.get("sha256"), sample.get("video")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(video, str) or sample.get("synthetic") is not False):
        raise ValueError("Public sample original recording provenance is invalid")
    row = {"source_sha256": digest, "source_name": Path(video).name,
           "source_path": video, "data_origin": "real", "source_kind": "recorded_video"}
    timestamp = matching[0].get("timestamp_s")
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        row["timestamp_s"] = str(timestamp)
    return row


def image_identity(root: Path, image_path: str) -> dict[str, str]:
    path = (root / image_path).resolve()
    return {"path": relative_image(root, image_path), "bytes": content_hash(path), "pixels": pixel_hash(path)}


def unique_images(root: Path, paths: list[str]) -> None:
    identities = [image_identity(root, path) for path in paths]
    for key in ("path", "bytes", "pixels"):
        if len({value[key] for value in identities}) != len(identities):
            raise ValueError("Evaluation/training images must have unique byte and decoded-pixel content; duplicate inflation is not allowed")
