"""Reserved acceptance labels are human-visible, not agent planning context."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from engine.eval.protocol import reserved_acceptance_paths
from spec.models import EvalDataset

if TYPE_CHECKING:
    from engine.service import WorkspaceService


def visible_dataset(service: WorkspaceService, project_id: str, dataset: EvalDataset) -> EvalDataset:
    reserved = reserved_acceptance_paths(service.root(project_id), service.annotations(project_id))
    return dataset.model_copy(update={"annotations": [row for row in dataset.annotations if row.image_path not in reserved]}, deep=True)


def save_unreviewed_dataset(service: WorkspaceService, project_id: str, dataset: EvalDataset) -> EvalDataset:
    current = service.annotations(project_id)
    reserved = reserved_acceptance_paths(service.root(project_id), current)
    root = service.root(project_id)
    def resolved(value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else root / path).resolve()
    originals = {resolved(row.image_path): row for row in current.annotations}
    for row in dataset.annotations:
        if row.image_path in reserved:
            original = originals.get(resolved(row.image_path))
            if original is None or row.model_copy(update={"image_path": original.image_path}) != original:
                raise ValueError("Agent tools cannot change reserved acceptance annotations")
    visible = [row for row in dataset.annotations if row.image_path not in reserved]
    if any(row.reviewed for row in visible):
        raise ValueError("Agents cannot mark labels reviewed. Request a human review in the app.")
    merged = dataset.model_copy(update={"annotations": visible + [row for row in current.annotations if row.image_path in reserved]})
    return visible_dataset(service, project_id, service.save_annotations(project_id, merged))
