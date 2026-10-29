"""Commit a prepared refinement under the workspace lock with failure rollback.

Approvals are revoked before document replacement. Cooperating API readers use the
same lock; a process crash may leave partial authoring files, but never a valid
approval for the changed graph. Ordinary write failures restore the original set.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from pydantic import BaseModel

from engine.datasets import DatasetMetadata
from engine.store.models import Project, now
from engine.store.repository import atomic_model
from spec.models import EvalDataset


def _restore(path: Path, value: bytes | None) -> None:
    if value is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
    try:
        with temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def commit_refinement(root: Path, project: Project, dataset: EvalDataset,
                      metadata: DatasetMetadata, *, labels_changed: bool,
                      classes_changed: bool) -> None:
    project.evaluations = []
    project.deployment_id = None
    project.approval_scope = None
    project.trial_limits = {}
    project.status = "building"
    project.updated_at = now()
    documents: dict[str, BaseModel] = {}
    if labels_changed:
        documents["annotations.json"] = dataset
    if labels_changed or classes_changed:
        metadata.fingerprint = hashlib.sha256(json.dumps({"media": project.media,
            "annotations": dataset.model_dump(mode="json"),
            "classes": [item.model_dump() for item in metadata.classes]}, sort_keys=True).encode()).hexdigest()
        metadata.revision += 1
        documents["dataset-metadata.json"] = metadata
    documents["project.json"] = project
    revoked = ("deployment.json", "eval-media.json")
    originals = {name: (root / name).read_bytes() if (root / name).exists() else None
                 for name in (*documents, *revoked)}
    try:
        for name in revoked:
            (root / name).unlink(missing_ok=True)
        for name, value in documents.items():
            atomic_model(root / name, value)
    except BaseException:
        # Restore authoring data first; restore approvals only after it all succeeds.
        for name in documents:
            _restore(root / name, originals[name])
        for name in revoked:
            _restore(root / name, originals[name])
        raise
