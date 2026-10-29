"""Verify the immutable, host-executed origin before importing a draft."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from engine.compiler import compile_pipeline
from engine.eval.hashes import spec_hash
from engine.investigations.media import DevelopmentMedia
from engine.investigations.probes import Artifacts
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.investigations.tools import InvestigationTools
from engine.platform.planning_options import validate_current_options
from engine.service import WorkspaceService
from spec.handoff import PrepareHandoff
from spec.investigation import ConstructWorkflow, Finish, WorkflowPreviewEvidence
from spec.model_bindings import validate_block_bindings
from spec.models import PipelineSpec, RunResult, SourceSpec
from spec.planning import CandidateModelSelection, PlanningOptions


def owned_file(path: Path, owner: Path) -> bytes:
    """Reject symlink components, traversal and oversized owned evidence."""
    relative = path.relative_to(owner)
    if owner.is_symlink() or any((owner / Path(*relative.parts[:n])).is_symlink()
                                 for n in range(1, len(relative.parts) + 1)):
        raise InvestigationConflict("Handoff evidence cannot contain symlinks")
    if not path.resolve().is_relative_to(owner.resolve()) or path.stat().st_size > 64 * 1024 * 1024:
        raise InvestigationConflict("Handoff evidence escaped its owner or exceeds the size limit")
    return path.read_bytes()


@dataclass(frozen=True)
class DraftEvidence:
    original: PipelineSpec
    candidate: PipelineSpec
    options: PlanningOptions
    bindings: list[CandidateModelSelection]
    objective: str
    revision: dict[str, Any]


def verify_draft(service: WorkspaceService, store: InvestigationStore, project_id: str,
                 task_id: str, request: PrepareHandoff) -> DraftEvidence:
    state = store.get(project_id, task_id)
    if (state.status not in {"draft_ready", "inconclusive"} or state.revision != request.expected_revision
            or state.pending_action_id or state.pending_model_call_id
            or state.selected_workflow_revision != request.workflow_revision_id
            or state.preview_observation_id != request.preview_observation_id):
        raise InvestigationConflict("The selected draft or investigation state changed; refresh before handoff")
    observation = store.get_observation(project_id, task_id, request.preview_observation_id)
    actions = store.actions(project_id, task_id)
    action = next((row for row in actions if row.id == observation.action_id), None)
    if (observation.status != "completed" or observation.result_type != "construct_workflow"
            or action is None or action.status != "completed" or action.observation_id != observation.id
            or not isinstance(action.action, ConstructWorkflow)):
        raise InvestigationConflict("The draft has no completed construction receipt")
    if state.status == "draft_ready" and not any(row.status == "completed" and isinstance(row.action, Finish)
               and row.action.outcome == "draft_ready" and row.action.workflow_revision_id == request.workflow_revision_id
               and observation.id in row.action.evidence_ids for row in actions):
        raise InvestigationConflict("The selected draft has no completed finish receipt")
    evidence = WorkflowPreviewEvidence.model_validate({key: observation.payload.get(key)
        for key in WorkflowPreviewEvidence.model_fields})
    if (evidence.workflow_revision_id != request.workflow_revision_id
            or evidence.preview_media_ids != action.action.media_ids):
        raise InvestigationConflict("The preview does not match the constructed draft")
    task_root = store.root(project_id, task_id)
    artifacts = Artifacts(task_root)

    def read(reference: Any) -> Any:
        if not isinstance(reference, dict) or reference.get("mime_type") != "application/json":
            raise InvestigationConflict("Missing typed workflow artifact reference")
        # Artifacts.read checks identifier/hash; check owner, declared size and MIME too.
        data = artifacts.read(reference)
        if len(data) != reference.get("bytes") or owned_file(artifacts.root / reference["artifact_id"], task_root) != data:
            raise InvestigationConflict("Workflow artifact size or ownership changed")
        return json.loads(data)

    revision = read(observation.payload.get("revision_artifact"))
    if (not isinstance(revision, dict) or revision.get("schema_version") != "a0.workflow.1"
            or revision.get("id") != request.workflow_revision_id or revision.get("project_id") != project_id
            or revision.get("task_id") != task_id or revision.get("action_id") != action.id
            or revision.get("spec_hash") != evidence.spec_hash
            or revision.get("preview_spec_hash") != evidence.spec_hash
            or revision.get("preview_media_ids") != evidence.preview_media_ids
            or revision.get("validated") is not True or revision.get("preview_success") is not True):
        raise InvestigationConflict("Workflow revision identity or preview receipt is invalid")
    revision_root = task_root / "workflows" / request.workflow_revision_id
    if json.loads(owned_file(revision_root / "version.json", task_root)) != {
            **revision, "revision_artifact": observation.payload["revision_artifact"]}:
        raise InvestigationConflict("Workflow version receipt changed")
    refs = revision["artifacts"]
    original = PipelineSpec.model_validate(read(refs["spec"]))
    options = PlanningOptions.model_validate(read(refs["options"]))
    bindings = TypeAdapter(list[CandidateModelSelection]).validate_python(read(refs["bindings"]))
    preview = RunResult.model_validate(read(refs["preview"]))
    if preview != evidence.preview or options.project_id != project_id:
        raise InvestigationConflict("Captured preview/options differ from this project's workflow")
    root = service.root(project_id)
    if original.inputs["source"] != SourceSpec(type="image_folder", path=(revision_root / "media").relative_to(root).as_posix()):
        raise InvestigationConflict("Workflow source is not its exact frozen preview directory")
    validate_current_options(service, options, [row.capability_id for row in bindings])
    validate_block_bindings(original, bindings, 0, options)
    tools = InvestigationTools(service, store)
    for capability, expected in revision["descriptor_hashes"].items():
        descriptor = tools._descriptor(capability)
        if descriptor.get("descriptor_hash") != expected or descriptor.get("probe_eligible") is not True:
            raise InvestigationConflict("A workflow capability changed; construct a fresh draft before handoff")
    if set(revision["descriptor_hashes"]) != {row.capability_id for row in bindings}:
        raise InvestigationConflict("Workflow model descriptor coverage is incomplete")
    compiled = compile_pipeline(original, root)
    if spec_hash(original, root) != evidence.spec_hash:
        raise InvestigationConflict("Workflow model, geometry or spec identity changed")
    sources = revision["input_refs"]
    if len(sources) != len(preview.frames):
        raise InvestigationConflict("Workflow source manifest is incomplete")
    media = DevelopmentMedia(service, project_id)
    for index, (source, frame) in enumerate(zip(sources, preview.frames, strict=True)):
        resolved = media.resolve(evidence.preview_media_ids[index], source["source_sha256"])
        frozen = revision_root / "media" / f"{index:02d}-{resolved.media_id}{resolved.path.suffix.lower()}"
        if (source["media_id"] != resolved.media_id or source["source_path"] != str(resolved.path)
                or source["pixels_sha256"] != resolved.pixels_sha256
                or source["preview_path"] != str(frozen) or frame.image_path != str(frozen)
                or frame.source_image_sha256 != resolved.source_sha256
                or hashlib.sha256(owned_file(frozen, task_root)).hexdigest() != resolved.source_sha256):
            raise InvestigationConflict("Original or frozen preview media changed")
        if ({row.block_id for row in frame.inferences} != {row.block_id for row in bindings}
                or len(frame.inferences) != len(bindings)):
            raise InvestigationConflict("Preview model binding coverage differs from the saved workflow")
        for inference in frame.inferences:
            if inference.result.identity.identity_hash != compiled.inference_identities[inference.block_id].identity_hash:
                raise InvestigationConflict("Preview model identity changed")
    candidate = original.model_copy(deep=True)
    candidate.inputs["source"] = SourceSpec(type="image_folder", path="media")
    validate_block_bindings(candidate, bindings, 0, options)
    return DraftEvidence(original, candidate, options, bindings, state.objective, revision)
