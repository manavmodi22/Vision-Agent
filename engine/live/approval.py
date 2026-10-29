"""Frame-boundary checks bind capture to a current approved workflow."""
from __future__ import annotations

from dataclasses import dataclass

from engine.eval import spec_hash
from engine.live.contracts import LiveError
from engine.media import media_fingerprint
from engine.service import WorkspaceService
from engine.store.models import Project
from spec.models import PipelineSpec


@dataclass(frozen=True)
class Approval:
    candidate: PipelineSpec
    spec_hash: str
    deployment_id: str | None
    dataset_hash: str | None
    media_hash: str | None
    protocol_hash: str | None = None
    approval_scope: str | None = None


def inspect(service: WorkspaceService, project_id: str, index: int, preview: bool) -> tuple[Approval, Project]:
    """Caller holds repository lock; this function never changes approval."""
    project = service.get_project(project_id)
    root = service.root(project_id)
    candidate = service.candidate(project_id, index)
    fingerprint = spec_hash(candidate, root)
    if preview:
        return Approval(candidate, fingerprint, None, None, None), project
    try:
        deployment = service.approved_deployment(project_id, index)
    except (ValueError, OSError) as error:
        raise LiveError(f"Live recording approval is stale or missing: {error}", 409) from error
    media_hash = media_fingerprint(project.media)
    return Approval(candidate, fingerprint, deployment.id, deployment.dataset_hash, media_hash,
                    deployment.protocol_hash, deployment.approval_scope), project


def recheck(service: WorkspaceService, project_id: str, index: int, preview: bool, approved: Approval) -> Project:
    current, project = inspect(service, project_id, index, preview)
    if current != approved:
        raise LiveError("Workflow, model or approval changed during live capture; session closed", 409)
    return project
