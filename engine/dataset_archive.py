"""Portable complete labels, matched to existing normalized image pixels."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image
from pydantic import Field, model_validator

from engine.datasets import (
    DataContract,
    DatasetClass,
    DatasetConflict,
    DatasetManifest,
    DatasetService,
)
from engine.eval.configuration import _read_configuration
from engine.eval.usage import exposure_map
from engine.evidence_metadata import image_identity, relative_image
from engine.models.artifacts import content_hash
from engine.store.repository import atomic_model
from spec.inference import SHA256
from spec.models import Annotation

if TYPE_CHECKING:
    from engine.service import WorkspaceService

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


class ArchivedImage(DataContract):
    file_name: str = Field(min_length=1, max_length=255)
    image_sha256: SHA256
    pixels_sha256: SHA256
    width: int = Field(gt=0, le=32768)
    height: int = Field(gt=0, le=32768)
    annotation: Annotation
    model_exposure_reasons: list[str] = Field(max_length=1000)

    @model_validator(mode="after")
    def portable_name(self) -> ArchivedImage:
        if (Path(self.file_name).name != self.file_name or self.file_name in {".", ".."}
                or "\\" in self.file_name or any(ord(c) < 32 for c in self.file_name)):
            raise ValueError("Archive image names must be simple filenames")
        if self.annotation.image_path != self.file_name:
            raise ValueError("Archived annotation must name its matching image")
        complete = {"image_path", "detections", "reviewed", "expected_texts", "proposal", "text_regions", "expected_text_source"}
        if not complete.issubset(self.annotation.model_fields_set):
            raise ValueError("Complete label archives must explicitly include every annotation field")
        if any(not reason.strip() or len(reason) > 1000 for reason in self.model_exposure_reasons):
            raise ValueError("Invalid archived model-exposure reason")
        return self


class LabelArchive(DataContract):
    schema_version: Literal["1"] = "1"
    coordinate_space: Literal["normalized_top_left_oriented_rgb"] = "normalized_top_left_oriented_rgb"
    classes: list[DatasetClass] = Field(default_factory=list, max_length=200)
    images: list[ArchivedImage] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def unique_entries(self) -> LabelArchive:
        if len({row.pixels_sha256 for row in self.images}) != len(self.images):
            raise ValueError("Archive has duplicate decoded image pixels")
        if len({row.file_name for row in self.images}) != len(self.images):
            raise ValueError("Archive image filenames must be unique")
        if (len({c.id for c in self.classes}) != len(self.classes)
                or len({c.name.casefold() for c in self.classes}) != len(self.classes)):
            raise ValueError("Archive classes must have unique IDs and names")
        declared = {c.name for c in self.classes}
        if any(d.label not in declared for row in self.images for d in row.annotation.detections):
            raise ValueError("Archived detection refers to an undeclared class")
        return self


def _has_labels(annotation: Annotation) -> bool:
    return bool(annotation.detections or annotation.text_regions or annotation.expected_texts
                or annotation.proposal or annotation.reviewed or annotation.expected_text_source != "manual")


def _stable_identity(root: Path, path: Path) -> dict[str, str]:
    identity = image_identity(root, str(path))
    if content_hash(path) != identity["bytes"]:
        raise ValueError("Image changed while transferring labels; retry after it is stable")
    return identity


class LabelArchiveService:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.datasets = DatasetService(service)

    def export_labels(self, project_id: str) -> LabelArchive:
        with self.service.repository.lock:
            root = self.service.root(project_id)
            manifest = self.datasets.manifest(project_id)
            dataset = self.service.annotations(project_id)
            configuration = _read_configuration(root, dataset)
            exposures = exposure_map(root, configuration.images)
            rows = {(root / row.image_path).resolve(): row for row in dataset.annotations}
            images = []
            for item in manifest.images:
                path = (root / item.image_path).resolve()
                identity = _stable_identity(root, path)
                annotation = Annotation.model_validate({**rows[path].model_dump(mode="json"), "image_path": path.name})
                images.append(ArchivedImage(file_name=path.name, image_sha256=identity["bytes"],
                    pixels_sha256=identity["pixels"], width=item.width, height=item.height,
                    annotation=annotation, model_exposure_reasons=exposures.get(relative_image(root, str(path)), [])))
            archive = LabelArchive(classes=manifest.classes, images=images)
            if len(archive.model_dump_json().encode()) > MAX_ARCHIVE_BYTES:
                raise ValueError("Label archive exceeds 32 MiB; export a smaller dataset")
            return archive

    def import_labels(self, project_id: str, filename: str, base_revision: int,
                      replace_existing: bool = False) -> DatasetManifest:
        source = Path(filename).expanduser().resolve(strict=True)
        if not source.is_file() or source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("Select a VisionApp label JSON file no larger than 32 MiB")
        with source.open("rb") as stream:
            payload = stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise ValueError("Label archive exceeds 32 MiB")
        archive = LabelArchive.model_validate_json(payload)
        if not {"schema_version", "coordinate_space"}.issubset(archive.model_fields_set):
            raise ValueError("Label archives must declare their schema version and coordinate space")
        with self.service.repository.lock:
            metadata = self.datasets._check_revision(project_id, base_revision)
            root = self.service.root(project_id)
            dataset = self.service.annotations(project_id)
            rows = {(root / row.image_path).resolve(): row for row in dataset.annotations}
            identities: dict[str, list[Path]] = {}
            initial_bytes: dict[Path, str] = {}
            for path in rows:
                identity = _stable_identity(root, path)
                initial_bytes[path] = identity["bytes"]
                identities.setdefault(identity["pixels"], []).append(path)
            classes = self._merge_classes(metadata.classes, archive.classes)
            imported_exposures: dict[str, list[str]] = {}
            replacements: dict[Path, Annotation] = {}
            for item in archive.images:
                matches = identities.get(item.pixels_sha256, [])
                if not matches:
                    raise ValueError(f"Import the matching image before its labels: {item.file_name}")
                if len(matches) != 1:
                    raise ValueError(f"Multiple imported images have matching pixels: {item.file_name}")
                path = matches[0]
                with Image.open(path) as image:
                    if image.size != (item.width, item.height) or image.getexif().get(274, 1) != 1:
                        raise ValueError("Archive dimensions/orientation differ from normalized imported image")
                if _has_labels(rows[path]) and not replace_existing:
                    raise DatasetConflict("Existing labels would be replaced; choose replacement explicitly")
                row = item.annotation.model_copy(deep=True, update={"image_path": rows[path].image_path, "reviewed": False})
                replacements[path] = row
                imported_exposures[row.image_path] = item.model_exposure_reasons
            dataset.annotations = [replacements.get((root / row.image_path).resolve(), row) for row in dataset.annotations]
            if any(content_hash(path) != initial_bytes[path] for path in replacements):
                raise ValueError("Image changed while transferring labels; retry after it is stable")
            self.service.save_annotations(project_id, dataset, imported_exposures=imported_exposures)
            metadata.classes = classes
            atomic_model(root / "dataset-metadata.json", metadata)
            return self.datasets.manifest(project_id)

    @staticmethod
    def _merge_classes(existing: list[DatasetClass], incoming: list[DatasetClass]) -> list[DatasetClass]:
        merged = [row.model_copy(deep=True) for row in existing]
        names = {row.name.casefold(): row.name for row in existing}
        ids = {row.id for row in existing}
        for item in incoming:
            if item.name.casefold() in names:
                if names[item.name.casefold()] != item.name:
                    raise ValueError("Imported class conflicts with existing class capitalization")
                continue
            row = item.model_copy(deep=True)
            if row.id in ids:
                row.id = uuid.uuid4().hex[:12]
            merged.append(row)
            names[row.name.casefold()] = row.name
            ids.add(row.id)
        if len(merged) > 200:
            raise ValueError("Imported labels would exceed 200 classes")
        return merged
