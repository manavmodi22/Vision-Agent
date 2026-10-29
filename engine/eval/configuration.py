"""CAS evidence assignments, preserving annotations and review state."""
from __future__ import annotations

from pathlib import Path

from filelock import FileLock
from pydantic import Field

from engine.evidence_metadata import relative_image, source_record
from engine.models.artifacts import canonical_hash
from engine.store.repository import atomic_model
from spec.evaluation import (
    EvaluationConfiguration,
    EvaluationConfigurationUpdate,
    EvidenceAssignment,
    EvidenceImage,
    EvidencePolicy,
)
from spec.models import Contract, EvalDataset


class StoredConfiguration(Contract):
    assignments: list[EvidenceAssignment] = Field(default_factory=list)
    policy: EvidencePolicy = Field(default_factory=EvidencePolicy)


def evidence_lock(root: Path) -> FileLock:
    folder = root / "evaluation"
    folder.mkdir(parents=True, exist_ok=True)
    return FileLock(folder / ".evidence.lock", timeout=30)


def _read_configuration(root: Path, dataset: EvalDataset) -> EvaluationConfiguration:
    path = root / "evaluation/config.json"
    saved = StoredConfiguration.model_validate_json(path.read_text()) if path.exists() else StoredConfiguration()
    assignments = {relative_image(root, item.image_path): item for item in saved.assignments}
    images = []
    fixture = (root / "synthetic-provenance.json").exists() or dataset.id == "synthetic-lanes-v1"
    for annotation in dataset.annotations:
        relative = relative_image(root, annotation.image_path)
        assignment = assignments.get(relative, EvidenceAssignment(image_path=relative))
        record = source_record(root, relative)
        synthetic = fixture or record.get("data_origin") == "synthetic"
        source_hash = record.get("source_sha256")
        if source_hash and (len(source_hash) != 64 or any(c not in "0123456789abcdef" for c in source_hash)):
            raise ValueError("Invalid recorded source content hash")
        images.append(EvidenceImage(image_path=relative, scene_group=assignment.scene_group,
            split=assignment.split, data_origin="synthetic" if synthetic else ("real" if record.get("data_origin") == "real" else assignment.data_origin),
            source_asset_id="sha256:" + source_hash if source_hash else None, source_sha256=source_hash,
            frame_index=int(record["frame_index"]) if "frame_index" in record else None,
            timestamp_s=float(record["timestamp_s"]) if "timestamp_s" in record else None,
            group_provenance="human_declared" if assignment.scene_group else ("source_record" if source_hash else "unknown")))
    revision = canonical_hash({"images": [item.model_dump(mode="json") for item in images],
                               "policy": saved.policy.model_dump(mode="json")})
    return EvaluationConfiguration(revision=revision, images=images, policy=saved.policy)


def read_configuration(root: Path, dataset: EvalDataset) -> EvaluationConfiguration:
    from engine.eval.usage import exposure_map
    result = _read_configuration(root, dataset)
    exposures = exposure_map(root, result.images)
    for image in result.images:
        image.exposure_reasons = exposures.get(image.image_path, [])
    return result


def stable_configuration_hash(root: Path, dataset: EvalDataset) -> str:
    return _read_configuration(root, dataset).revision


def save_configuration(root: Path, dataset: EvalDataset,
                       request: EvaluationConfigurationUpdate) -> EvaluationConfiguration:
    with evidence_lock(root):
        current = _read_configuration(root, dataset)
        if request.expected_revision != current.revision:
            raise ValueError("Evaluation configuration changed; reload before saving")
        from engine.eval.usage import preserve_legacy_usage
        preserve_legacy_usage(root, current.images)
        rows = {item.image_path: item for item in current.images}
        merged = {item.image_path: EvidenceAssignment.model_validate(item.model_dump(include={
            "image_path", "scene_group", "split", "data_origin"})) for item in current.images}
        for item in request.assignments:
            relative = relative_image(root, item.image_path)
            if relative not in rows:
                raise ValueError("Evidence assignment refers to an image outside this dataset")
            if rows[relative].data_origin == "synthetic" and item.data_origin != "synthetic":
                raise ValueError("Known synthetic images cannot be reclassified as real")
            if item.scene_group is not None and not item.scene_group.strip():
                raise ValueError("Scene group cannot be blank")
            merged[relative] = item.model_copy(update={"image_path": relative})
        atomic_model(root / "evaluation/config.json", StoredConfiguration(
            assignments=list(merged.values()), policy=request.policy))
        return read_configuration(root, dataset)


def reserved_acceptance_paths(root: Path, dataset: EvalDataset) -> set[str]:
    images = _read_configuration(root, dataset).images
    paths = {other.image_path for row in images if row.split == "acceptance"
             for other in connected_group(row, images)}
    return paths | {str((root / path).resolve()) for path in paths}


def selected_paths(root: Path, dataset: EvalDataset, purpose: str) -> list[str]:
    config = _read_configuration(root, dataset)
    if purpose == "acceptance":
        return [row.image_path for row in config.images if row.split == "acceptance"]
    explicit = [row.image_path for row in config.images if row.split == "validation"]
    if explicit:
        return explicit
    allowed = {row.image_path for row in config.images if row.split not in {"acceptance", "train"}}
    holdout_path = root / "active-holdout.json"
    if holdout_path.exists():
        holdout = EvalDataset.model_validate_json(holdout_path.read_text())
        names = [relative_image(root, row.image_path) for row in holdout.annotations]
        if any(name not in {row.image_path for row in config.images} for name in names):
            raise ValueError("The legacy validation holdout is missing images")
        return [name for name in names if name in allowed]
    return [relative_image(root, row.image_path) for row in dataset.annotations
            if row.reviewed and relative_image(root, row.image_path) in allowed]


def group_keys(image: EvidenceImage) -> set[str]:
    return ({"scene:" + image.scene_group} if image.scene_group else set()) | (
        {"source:" + image.source_sha256} if image.source_sha256 else set())


def connected_group(image: EvidenceImage, images: list[EvidenceImage]) -> list[EvidenceImage]:
    keys = group_keys(image)
    selected = {image.image_path}
    while True:
        joined = [row for row in images if row.image_path in selected or group_keys(row) & keys]
        expanded = set().union(*(group_keys(row) for row in joined))
        if expanded == keys:
            return joined
        keys = expanded
        selected = {row.image_path for row in joined}


def project_dataset(root: Path) -> EvalDataset:
    path = root / "annotations.json"
    return EvalDataset.model_validate_json(path.read_text()) if path.exists() else EvalDataset(id="unregistered")
