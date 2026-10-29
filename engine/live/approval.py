"""Frame-boundary checks bind capture to a current approved workflow."""
from __future__ import annotations

import json
from dataclasses import dataclass

from engine.eval import dataset_hash, spec_hash
from engine.live.contracts import LiveError
from engine.media import media_fingerprint
from engine.service import WorkspaceService
from engine.store.models import Deployment, Project
from spec.models import PipelineSpec


@dataclass(frozen=True)
class Approval:
    candidate: PipelineSpec
    spec_hash: str
    deployment_id: str | None
    dataset_hash: str | None
    media_hash: str | None


def inspect(service: WorkspaceService, project_id: str, index: int, preview: bool) -> tuple[Approval, Project]:
    """Caller holds repository lock; this function never changes approval."""
    project = service.get_project(project_id)
    root = service.root(project_id)
    candidate = service.candidate(project_id, index)
    fingerprint = spec_hash(candidate, root)
    if preview:
        return Approval(candidate, fingerprint, None, None, None), project
    path = root / "deployment.json"
    if not project.deployment_id or not path.is_file():
        raise LiveError("Approve deployment before live recording, or explicitly choose preview_only", 409)
    deployment = Deployment.model_validate_json(path.read_text())
    labels = service.evaluation_annotations(project_id)
    label_hash = dataset_hash(labels, root)
    media_hash = media_fingerprint(project.media)
    evidence_path = root / "eval-media.json"
    evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {}
    if (deployment.id != project.deployment_id or deployment.candidate_index != index
            or deployment.spec_hash != fingerprint or deployment.dataset_hash != label_hash
            or not all(item.reviewed for item in labels.annotations)
            or evidence.get(fingerprint) != media_hash):
        raise LiveError("Live recording approval is stale; evaluate and approve the current workflow", 409)
    return Approval(candidate, fingerprint, deployment.id, label_hash, media_hash), project


def recheck(service: WorkspaceService, project_id: str, index: int, preview: bool, approved: Approval) -> Project:
    current, project = inspect(service, project_id, index, preview)
    if (current.spec_hash, current.deployment_id, current.dataset_hash, current.media_hash) != (
            approved.spec_hash, approved.deployment_id, approved.dataset_hash, approved.media_hash):
        raise LiveError("Workflow, model or approval changed during live capture; session closed", 409)
    return project
