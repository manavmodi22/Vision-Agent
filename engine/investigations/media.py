"""Opaque development-media authority and conservative pixel exposure accounting."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from engine.eval.configuration import _read_configuration, evidence_lock
from engine.eval.protocol import reserved_acceptance_paths
from engine.eval.usage import ExposureSnapshot
from engine.evidence_metadata import pixel_hash_image, relative_image
from engine.models.artifacts import content_hash
from engine.service import WorkspaceService
from engine.store.repository import atomic_model


@dataclass(frozen=True)
class MediaInput:
    media_id: str
    path: Path
    source_sha256: str
    pixels_sha256: str
    image: Image.Image

    def metadata(self) -> dict[str, object]:
        return {"media_id": self.media_id, "source_sha256": self.source_sha256,
                "pixels_sha256": self.pixels_sha256, "width": self.image.width,
                "height": self.image.height, "membership": "development"}


def media_identifier(project_id: str, relative: str) -> str:
    return "media-" + hashlib.sha256((project_id + "\0" + relative).encode()).hexdigest()[:32]


class DevelopmentMedia:
    def __init__(self, service: WorkspaceService, project_id: str) -> None:
        self.service, self.project_id = service, project_id
        self.root = service.root(project_id)

    def _paths(self) -> dict[str, Path]:
        dataset = self.service.annotations(self.project_id)
        reserved = reserved_acceptance_paths(self.root, dataset)
        result = {}
        for raw in self.service.get_project(self.project_id).media:
            relative = relative_image(self.root, raw)
            path = (self.root / relative).resolve()
            if str(path) not in reserved and relative not in reserved:
                result[media_identifier(self.project_id, relative)] = path
        return result

    def identifiers(self) -> list[str]:
        with self.service.repository.lock:
            return sorted(self._paths())

    def _read(self, media_id: str, expected_sha256: str | None = None) -> MediaInput:
        path = self._paths().get(media_id)
        if path is None:
            raise ValueError("Media ID is not an available development image in this project")
        digest = content_hash(path)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("Source image changed since inspection; inspect the current media again")
        with Image.open(path) as opened:
            if min(opened.size) <= 0 or max(opened.size) > 32768 or opened.width * opened.height > 40_000_000:
                raise ValueError("Development images must contain at most 40 million pixels")
            image = ImageOps.exif_transpose(opened).convert("RGB").copy()
        if content_hash(path) != digest:
            raise ValueError("Source image changed while reading; no pixels were delivered")
        pixels = pixel_hash_image(image)
        # Existing reservations cover declared scene/source groups. Also exclude
        # copied bytes/pixels: a fresh opaque ID cannot hide reserved content.
        dataset = self.service.annotations(self.project_id)
        reserved = reserved_acceptance_paths(self.root, dataset)
        for raw in sorted({str((self.root / name).resolve()) for name in reserved}):
            held = Path(raw)
            if content_hash(held) == digest:
                raise ValueError("Development image duplicates reserved acceptance content")
            with Image.open(held) as held_image:
                if pixel_hash_image(held_image) == pixels:
                    raise ValueError("Development pixels duplicate reserved acceptance content")
        return MediaInput(media_id, path, digest, pixels, image)

    def resolve(self, media_id: str, expected_sha256: str | None = None) -> MediaInput:
        with self.service.repository.lock, evidence_lock(self.root):
            return self._read(media_id, expected_sha256)

    def expose(self, media: MediaInput, pixels: Image.Image, purpose: str) -> None:
        """Authorize and append exposure under the same evidence assignment lock.

        Uses the existing exposure token/group calculation. Calling mark_usage
        while holding a second FileLock instance would deadlock, so commit its
        same ledger transaction here while the reservation check remains locked.
        """
        with self.service.repository.lock, evidence_lock(self.root):
            self._read(media.media_id, media.source_sha256)
            rows = _read_configuration(self.root, self.service.annotations(self.project_id)).images
            snapshot = ExposureSnapshot(self.root, rows)
            relative = relative_image(self.root, str(media.path))
            tokens = set(snapshot.tokens.get(relative, set()))
            tokens.update({"bytes:" + media.source_sha256, "pixels:" + media.pixels_sha256,
                           "pixels:" + pixel_hash_image(pixels)})
            if len(set(snapshot.ledger.uses) | tokens) > 200000:
                raise ValueError("Project exposure ledger is full")
            for token in tokens:
                snapshot.ledger.uses[token] = sorted(set(snapshot.ledger.uses.get(token, [])) |
                                                    {"Model use: " + purpose[:120]})
            atomic_model(self.root / "evaluation/usage.json", snapshot.ledger)
