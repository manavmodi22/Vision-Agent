"""Dataset authoring with optimistic edits, class ontology and portable COCO boxes."""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from engine.eval import dataset_hash
from engine.evidence_metadata import pixel_hash as pixel_hash
from engine.media import import_paths
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.models import Annotation, Detection, EvalDataset

if TYPE_CHECKING:
    from engine.service import WorkspaceService

PALETTE = ["#43C6AC", "#609CFF", "#E8B86D", "#BF8CF2", "#F1849C", "#66CCD9"]


class DatasetConflict(ValueError):
    pass


class DataContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetClass(DataContract):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")

    @model_validator(mode="after")
    def clean_name(self) -> DatasetClass:
        self.name = self.name.strip()
        if not self.name or any(ord(c) < 32 for c in self.name):
            raise ValueError("Class names cannot be blank or contain control characters")
        return self


class DatasetImage(DataContract):
    id: str
    image_path: str
    width: int
    height: int
    reviewed: bool
    annotation_count: int
    text_region_count: int = 0
    split: Literal["train", "validation", "test", "acceptance", "unassigned"] = "unassigned"
    source_asset_id: str | None = None
    source_sha256: str | None = None
    frame_index: int | None = None
    timestamp_s: float | None = None
    scene_group: str | None = None
    data_origin: Literal["unknown", "real", "synthetic"] = "unknown"
    group_provenance: Literal["unknown", "source_record", "human_declared"] = "unknown"


class DatasetManifest(DataContract):
    revision: int
    classes: list[DatasetClass]
    images: list[DatasetImage]


class DatasetImageDocument(DataContract):
    revision: int
    annotation: Annotation


class DatasetMetadata(DataContract):
    revision: int = 0
    fingerprint: str = ""
    classes: list[DatasetClass] = Field(default_factory=list)


class DatasetVersion(DataContract):
    format_version: Literal["1", "2"] = "1"
    id: str
    name: str
    created_at: str
    revision: int
    image_count: int
    reviewed_count: int
    annotation_count: int
    text_region_count: int = 0
    dataset_hash: str
    source_dataset_hash: str | None = None
    classes: list[DatasetClass]


class CocoImage(BaseModel):
    id: int
    file_name: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CocoCategory(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=80)


class CocoAnnotation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: int
    image_id: int
    category_id: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    iscrowd: int = 0


class CocoDataset(BaseModel):
    images: list[CocoImage] = Field(min_length=1, max_length=5000)
    categories: list[CocoCategory] = Field(max_length=200)
    annotations: list[CocoAnnotation] = Field(max_length=500000)


def image_id(path: str, root: Path) -> str:
    relative = (root / path).resolve().relative_to(root.resolve())
    return hashlib.sha256(str(relative).encode()).hexdigest()[:16]


class DatasetService:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def _sync(self, project_id: str) -> DatasetMetadata:
        root = self.service.root(project_id)
        path = root / "dataset-metadata.json"
        metadata = DatasetMetadata.model_validate_json(path.read_text()) if path.exists() else DatasetMetadata()
        dataset = self.service.annotations(project_id)
        labels = sorted({box.label for row in dataset.annotations for box in row.detections})
        existing = {item.name for item in metadata.classes}
        for label in labels:
            if label not in existing:
                metadata.classes.append(DatasetClass(id=uuid.uuid4().hex[:12], name=label,
                                                     color=PALETTE[len(metadata.classes) % len(PALETTE)]))
        project = self.service.get_project(project_id)
        # Changes through legacy tools/import/training are also visible to revisioned editors.
        fingerprint = hashlib.sha256(json.dumps({"media": project.media,
            "annotations": dataset.model_dump(mode="json"),
            "classes": [c.model_dump() for c in metadata.classes]}, sort_keys=True).encode()).hexdigest()
        if fingerprint != metadata.fingerprint:
            metadata.revision += 1
            metadata.fingerprint = fingerprint
            atomic_model(path, metadata)
        return metadata

    def manifest(self, project_id: str) -> DatasetManifest:
        with self.service.repository.lock:
            metadata = self._sync(project_id)
            root = self.service.root(project_id)
            from engine.eval.configuration import _read_configuration
            evidence = {str((root / row.image_path).resolve()): row for row in
                        _read_configuration(root, self.service.annotations(project_id)).images}
            annotations = {(root / a.image_path).resolve(): a for a in self.service.annotations(project_id).annotations}
            holdout_path = root / "active-holdout.json"
            holdout = ({(root / a.image_path).resolve() for a in EvalDataset.model_validate_json(holdout_path.read_text()).annotations}
                       if holdout_path.exists() else set())
            images = []
            for filename in self.service.get_project(project_id).media:
                path = (root / filename).resolve()
                with Image.open(path) as image:
                    width, height = image.size
                annotation = annotations.get(path, Annotation(image_path=filename))
                row = evidence.get(str(path))
                images.append(DatasetImage(id=image_id(filename, root), image_path=str(path),
                    width=width, height=height, reviewed=annotation.reviewed,
                    annotation_count=len(annotation.detections),
                    text_region_count=len(annotation.text_regions),
                    split=row.split if row and row.split != "unassigned" else ("validation" if path in holdout else ("train" if holdout else "unassigned")),
                    **(row.model_dump(include={"source_asset_id", "source_sha256", "frame_index", "timestamp_s",
                                               "scene_group", "data_origin", "group_provenance"}) if row else {})))
            return DatasetManifest(revision=metadata.revision, classes=metadata.classes, images=images)

    def image(self, project_id: str, selected_id: str) -> DatasetImageDocument:
        with self.service.repository.lock:
            metadata = self._sync(project_id)
            root = self.service.root(project_id)
            for annotation in self.service.annotations(project_id).annotations:
                if image_id(annotation.image_path, root) == selected_id:
                    return DatasetImageDocument(revision=metadata.revision, annotation=annotation)
            raise FileNotFoundError("Dataset image not found")

    def _check_revision(self, project_id: str, revision: int) -> DatasetMetadata:
        metadata = self._sync(project_id)
        if metadata.revision != revision:
            raise DatasetConflict("Dataset changed since this image was loaded. Reload before saving your edit.")
        return metadata

    def save_image(self, project_id: str, selected_id: str, base_revision: int,
                   annotation: Annotation) -> DatasetImageDocument:
        with self.service.repository.lock:
            metadata = self._check_revision(project_id, base_revision)
            current = self.image(project_id, selected_id).annotation
            root = self.service.root(project_id)
            if (root / current.image_path).resolve() != (root / annotation.image_path).resolve():
                raise ValueError("An image edit cannot change its source image")
            if {d.label for d in annotation.detections} - {c.name for c in metadata.classes}:
                raise ValueError("Add the object class before labeling it")
            annotation = annotation.model_copy(update={"image_path": current.image_path})
            dataset = self.service.annotations(project_id)
            dataset.annotations = [annotation if image_id(row.image_path, root) == selected_id else row
                                   for row in dataset.annotations]
            self.service.save_annotations(project_id, dataset)
            return self.image(project_id, selected_id)

    def save_classes(self, project_id: str, base_revision: int,
                     classes: list[DatasetClass]) -> DatasetManifest:
        with self.service.repository.lock:
            metadata = self._check_revision(project_id, base_revision)
            if len(classes) > 200 or len({c.id for c in classes}) != len(classes) or len({c.name.casefold() for c in classes}) != len(classes):
                raise ValueError("Use up to 200 uniquely named classes with unique IDs")
            dataset = self.service.annotations(project_id)
            by_id = {c.id: c for c in classes}
            renames = {old.name: by_id[old.id].name for old in metadata.classes if old.id in by_id}
            used = {d.label for row in dataset.annotations for d in row.detections}
            if used - set(renames):
                raise ValueError("Remove or reassign annotations before deleting their class")
            for row in dataset.annotations:
                for detection in row.detections:
                    if detection.label != renames[detection.label]:
                        row.reviewed = False
                    detection.label = renames[detection.label]
            metadata.classes = classes
            root = self.service.root(project_id)
            atomic_model(root / "dataset-metadata.json", metadata)
            if dataset.annotations:
                self.service.save_annotations(project_id, dataset)
            return self.manifest(project_id)

    def freeze_holdout(self, project_id: str, selected_ids: list[str]) -> DatasetManifest:
        with self.service.repository.lock:
            root = self.service.root(project_id)
            selected = set(selected_ids)
            if not 10 <= len(selected) <= 50 or len(selected) != len(selected_ids):
                raise ValueError("Select 10–50 distinct reviewed images for evaluation")
            rows = [a for a in self.service.annotations(project_id).annotations if image_id(a.image_path, root) in selected]
            if len(rows) != len(selected) or not all(a.reviewed for a in rows):
                raise ValueError("Every holdout image must exist and be reviewed")
            atomic_model(root / "active-holdout.json", EvalDataset(id=f"{project_id}-holdout", annotations=rows))
            project = self.service.get_project(project_id)
            self.service.invalidate(project)
            self.service.repository.save(project)
            return self.manifest(project_id)

    def export_coco(self, project_id: str) -> dict[str, JsonValue]:
        with self.service.repository.lock:
            manifest = self.manifest(project_id)
            root = self.service.root(project_id)
            rows = {image_id(a.image_path, root): a for a in self.service.annotations(project_id).annotations}
            categories = {item.name: index + 1 for index, item in enumerate(manifest.classes)}
            images: list[JsonValue] = []
            boxes: list[JsonValue] = []
            for index, item in enumerate(manifest.images, 1):
                row = rows[item.id]
                images.append({"id": index, "file_name": Path(item.image_path).name, "width": item.width,
                    "height": item.height, "visionapp_reviewed": row.reviewed, "split": item.split})
                for detection in row.detections:
                    x1, y1, x2, y2 = detection.box
                    width, height = (x2 - x1) * item.width, (y2 - y1) * item.height
                    boxes.append({"id": len(boxes) + 1, "image_id": index, "category_id": categories[detection.label],
                        "bbox": [x1 * item.width, y1 * item.height, width, height],
                        "area": width * height, "iscrowd": 0})
            return {"info": {"description": "VisionApp bounding-box dataset", "revision": manifest.revision},
                    "images": images, "annotations": boxes,
                    "categories": [{"id": categories[item.name], "name": item.name} for item in manifest.classes]}

    def import_coco(self, project_id: str, filename: str, replace_existing: bool = False) -> DatasetManifest:
        source = Path(filename).expanduser().resolve(strict=True)
        if not source.is_file() or source.stat().st_size > 100_000_000:
            raise ValueError("Select a COCO JSON file smaller than 100 MB")
        coco = CocoDataset.model_validate_json(source.read_text())
        if len({i.id for i in coco.images}) != len(coco.images) or len({c.id for c in coco.categories}) != len(coco.categories):
            raise ValueError("COCO image and category IDs must be unique")
        if len({i.file_name for i in coco.images}) != len(coco.images):
            raise ValueError("COCO image filenames must be unique")
        if len({a.id for a in coco.annotations}) != len(coco.annotations):
            raise ValueError("COCO annotation IDs must be unique")
        category_names = {c.id: c.name.strip() for c in coco.categories}
        if len(set(category_names.values())) != len(category_names) or not all(category_names.values()):
            raise ValueError("COCO class names must be unique and nonempty")
        with self.service.repository.lock:
            project = self.service.get_project(project_id)
            if project.fixture:
                raise ValueError("Import datasets into a real project, separate from fixtures")
            root = self.service.root(project_id)
            existing = {Path(p).name: p for p in project.media}
            source_map_path = root / "media" / "media-sources.json"
            source_map = json.loads(source_map_path.read_text()) if source_map_path.exists() else {}
            if not isinstance(source_map, dict) or any(not isinstance(value, dict) for value in source_map.values()):
                raise ValueError("Media source provenance is invalid")
            pixel_hashes: dict[str, str] = {}
            claimed_paths: set[Path] = set()
            previous = self.service.annotations(project_id)
            rows = {(root / a.image_path).resolve(): a for a in previous.annotations}
            planned: dict[int, tuple[Path, Annotation, bool]] = {}
            for item in coco.images:
                relative = Path(item.file_name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("COCO image names must be relative paths within the dataset folder")
                target = (source.parent / relative).resolve()
                if not target.is_relative_to(source.parent):
                    raise ValueError("COCO image resolves outside the dataset folder")
                matched = existing.get(item.file_name)
                if not matched:
                    if target.is_file():
                        with Image.open(target) as original_image:
                            if original_image.getexif().get(274, 1) != 1:
                                raise ValueError("Normalize EXIF orientation before importing COCO annotations")
                        fingerprint = pixel_hash(target)
                        for imported in project.media:
                            if imported not in pixel_hashes:
                                pixel_hashes[imported] = pixel_hash(Path(imported))
                        matches = [p for p, digest in pixel_hashes.items() if digest == fingerprint]
                    else:
                        if any(provenance.get("source_name") == relative.name and provenance.get("source_orientation", "1") != "1"
                               for provenance in source_map.values()):
                            raise ValueError("Normalize EXIF orientation before importing COCO annotations")
                        matches = [existing[name] for name, provenance in source_map.items()
                                   if name in existing and provenance.get("source_name") == relative.name]
                    if len(matches) > 1:
                        raise ValueError("COCO image matches multiple imported images; use the exported unique filename")
                    matched = matches[0] if matches else None
                if matched:
                    target = Path(matched)
                    if target.resolve() in claimed_paths:
                        raise ValueError("Multiple COCO images refer to the same imported image")
                    claimed_paths.add(target.resolve())
                if not target.is_file():
                    raise ValueError(f"COCO image not found: {item.file_name}")
                with Image.open(target) as image:
                    if image.size != (item.width, item.height):
                        raise ValueError(f"COCO dimensions differ from the image: {item.file_name}")
                    if image.getexif().get(274, 1) != 1:
                        raise ValueError("Normalize EXIF orientation before importing COCO annotations")
                old = rows.get(target.resolve())
                if old and (old.detections or old.reviewed) and not replace_existing:
                    raise ValueError("Existing labels would be replaced; choose replace_existing explicitly")
                replacement = (old.model_copy(deep=True, update={"detections": [], "reviewed": False, "proposal": None})
                               if old else Annotation(image_path=str(target)))
                planned[item.id] = (target, replacement, bool(matched))
            dims = {i.id: (i.width, i.height) for i in coco.images}
            for box in coco.annotations:
                if box.image_id not in planned or box.category_id not in category_names:
                    raise ValueError("COCO annotation refers to a missing image or class")
                if box.iscrowd:
                    raise ValueError("Crowd regions cannot be treated as individual object boxes")
                width, height = dims[box.image_id]
                x, y, w, h = box.bbox
                planned[box.image_id][1].detections.append(Detection(label=category_names[box.category_id], confidence=1,
                    box=[x / width, y / height, (x + w) / width, (y + h) / height]))
            if len(project.media) + sum(not matched for _, _, matched in planned.values()) > 5000:
                raise ValueError("A dataset currently supports up to 5,000 images")
            created: list[str] = []
            try:
                for target, annotation, already_imported in planned.values():
                    if not already_imported:
                        imported = import_paths([str(target)], root / "media", 1)[0]
                        created.append(imported)
                        project.media.append(imported)
                        annotation.image_path = imported
                    rows[Path(annotation.image_path).resolve()] = annotation
                from engine.annotation_edits import normalize_annotation_edits
                from engine.eval.usage import preserve_annotation_usage

                updated = normalize_annotation_edits(root, previous,
                    EvalDataset(id=f"{project_id}-v1", annotations=list(rows.values())))
                preserve_annotation_usage(root, previous, updated)
                atomic_model(root / "annotations.json", updated)
                self.service.invalidate(project)
                self.service.repository.save(project)
            except Exception:
                for path in created:
                    Path(path).unlink(missing_ok=True)
                raise
            return self.manifest(project_id)

    def versions(self, project_id: str) -> list[DatasetVersion]:
        return sorted((DatasetVersion.model_validate_json(path.read_text())
                       for path in (self.service.root(project_id) / "dataset-versions").glob("*/version.json")),
                      key=lambda item: item.created_at, reverse=True)

    def create_version(self, project_id: str, name: str) -> DatasetVersion:
        if not name.strip() or len(name) > 120:
            raise ValueError("Version name must contain 1–120 characters")
        with self.service.repository.lock:
            root = self.service.root(project_id)
            manifest = self.manifest(project_id)
            dataset = self.service.annotations(project_id)
            if not dataset.annotations:
                raise ValueError("Import images before creating a dataset version")
            version = DatasetVersion(format_version="2", id=uuid.uuid4().hex[:16], name=name.strip(), created_at=now(),
                revision=manifest.revision, image_count=len(manifest.images),
                reviewed_count=sum(i.reviewed for i in manifest.images),
                annotation_count=sum(i.annotation_count for i in manifest.images),
                text_region_count=sum(i.text_region_count for i in manifest.images),
                dataset_hash="", source_dataset_hash=dataset_hash(dataset, root), classes=manifest.classes)
            folder = root / "dataset-versions" / version.id
            temporary = folder.with_name("." + version.id + ".tmp")
            (temporary / "images").mkdir(parents=True)
            try:
                for item in manifest.images:
                    shutil.copy2(root / item.image_path, temporary / "images" / Path(item.image_path).name)
                portable = dataset.model_copy(deep=True)
                for row in portable.annotations:
                    row.image_path = "images/" + Path(row.image_path).name
                atomic_model(temporary / "annotations.json", portable)
                version.dataset_hash = dataset_hash(portable, temporary)
                from engine.dataset_archive import LabelArchiveService

                atomic_model(temporary / "labels.vision-labels.json", LabelArchiveService(self.service).export_labels(project_id))
                coco = self.export_coco(project_id)
                coco_images = coco["images"]
                assert isinstance(coco_images, list)
                for coco_image in coco_images:
                    assert isinstance(coco_image, dict)
                    coco_image["file_name"] = "images/" + str(coco_image["file_name"])
                (temporary / "coco.json").write_text(json.dumps(coco, indent=2))
                portable_manifest = manifest.model_copy(deep=True)
                for item in portable_manifest.images:
                    item.image_path = "images/" + Path(item.image_path).name
                atomic_model(temporary / "manifest.json", portable_manifest)
                atomic_model(temporary / "version.json", version)
                temporary.rename(folder)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            return version
