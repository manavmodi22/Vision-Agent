"""Task-owned draft construction with actual, explicitly selected development previews."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from agent.graph_authoring import compose_graph, graph_model_selections
from engine.capabilities import validate_experiment_capabilities
from engine.compiler import compile_pipeline
from engine.eval.hashes import spec_hash
from engine.investigations.media import DevelopmentMedia, MediaInput
from engine.investigations.probes import JSON_OBJECT, Artifacts
from engine.investigations.store import InvestigationStore
from engine.investigations.tools import InvestigationTools, ToolOutcome
from engine.platform.planning_options import planning_options, validate_current_options
from engine.runtime import run_pipeline
from engine.runtime.media import IMAGE_EXTENSIONS
from engine.service import WorkspaceService
from engine.zones import read_zone_state
from spec.investigation import ConstructWorkflow
from spec.model_bindings import validate_block_bindings


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _write(path: Path, data: bytes) -> None:
    """A fresh revision never overwrites an existing input or receipt."""
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _reserved(store: InvestigationStore, project_id: str, task_id: str,
              action_id: str, action: ConstructWorkflow) -> None:
    state = store.get(project_id, task_id)
    receipt = next((row for row in store.actions(project_id, task_id) if row.id == action_id), None)
    if (state.status != "running" or state.stage != "workflow" or state.pending_action_id != action_id
            or receipt is None or receipt.status != "reserved" or receipt.action != action):
        raise ValueError("Workflow construction requires the current reserved workflow-stage action")


def _parent(store: InvestigationStore, project_id: str, task_id: str,
            action: ConstructWorkflow, artifacts: Artifacts) -> None:
    for identifier in action.evidence_ids:
        store.get_observation(project_id, task_id, identifier)
    if action.parent_revision_id is None:
        return
    prior = next((row for row in store.observations(project_id, task_id)
                  if row.status == "completed" and row.result_type == "construct_workflow"
                  and row.payload.get("workflow_revision_id") == action.parent_revision_id
                  and row.payload.get("validated") is True and row.payload.get("preview_success") is True), None)
    if prior is None or not isinstance(reference := prior.payload.get("revision_artifact"), dict):
        raise ValueError("Parent revision is not a successful previewed workflow in this investigation")
    saved = json.loads(artifacts.read(reference))
    if (saved.get("id") != action.parent_revision_id or saved.get("project_id") != project_id
            or saved.get("task_id") != task_id):
        raise ValueError("Parent workflow revision ownership is invalid")


def _inputs(media: DevelopmentMedia, action: ConstructWorkflow, directory: Path) -> tuple[list[MediaInput], list[JsonValue]]:
    if not 1 <= len(action.media_ids) <= 3 or len(set(action.media_ids)) != len(action.media_ids):
        raise ValueError("Select one to three distinct development media IDs")
    sources = [media.resolve(identifier) for identifier in action.media_ids]
    directory.mkdir()
    references: list[JsonValue] = []
    for index, source in enumerate(sources):
        suffix = source.path.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS or source.path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Workflow previews require supported development images of at most 64 MiB each")
        with source.path.open("rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != source.source_sha256:
            raise ValueError("Source image changed while freezing the selected preview input")
        path = directory / f"{index:02d}-{source.media_id}{suffix}"
        _write(path, raw)
        references.append(JSON_OBJECT.validate_python({**source.metadata(),
            "source_path": str(source.path), "preview_path": str(path), "preview_source_sha256": source.source_sha256}))
    return sources, references


def construct_workflow(service: WorkspaceService, store: InvestigationStore, project_id: str,
                       task_id: str, action_id: str, action: ConstructWorkflow) -> ToolOutcome:
    """Construct/preview one model-chosen graph; the coordinator commits task state.

    Call in the owned deadline-controlled worker. This function never saves project
    candidates, reviews, evaluations, approvals, deployment state or event records.
    """
    started = time.perf_counter()
    payload: dict[str, JsonValue] = {"executed": False, "validated": False, "preview_success": False}
    artifacts: Artifacts | None = None
    stage = "authorization"
    try:
        action = ConstructWorkflow.model_validate(action.model_dump(mode="json"))
        _reserved(store, project_id, task_id, action_id, action)
        if any(node.type == "resize" and node.width * node.height > 40_000_000 for node in action.graph.nodes):
            raise ValueError("Workflow resize inputs are limited to 40 million pixels")
        state = store.get(project_id, task_id)
        task_root = store.root(project_id, task_id)
        artifacts = Artifacts(task_root)
        _parent(store, project_id, task_id, action, artifacts)
        proposal_ref = artifacts.write(_encoded(action.model_dump(mode="json")), "application/json")
        payload["proposal_artifact"] = proposal_ref
        payload["artifact_refs"] = [proposal_ref]

        options = planning_options(service, project_id, request="\n".join([state.objective, *state.user_answers]))
        bindings = graph_model_selections([action.graph], options)
        tools = InvestigationTools(service, store)
        observations = store.observations(project_id, task_id)
        descriptor_hashes: dict[str, JsonValue] = {}
        for identifier in sorted({row.capability_id for row in bindings}):
            inspected = None
            for row in reversed(observations):
                saved = row.payload.get("descriptor")
                if (row.result_type == "inspect_capability" and row.status == "completed"
                        and isinstance(saved, dict) and saved.get("id") == identifier):
                    inspected = saved
                    break
            if not isinstance(inspected, dict):
                raise ValueError(f"Inspect capability {identifier} in this investigation before constructing its workflow")
            current = tools._descriptor(identifier)
            if current.get("descriptor_hash") != inspected.get("descriptor_hash"):
                raise ValueError(f"Capability {identifier} changed; inspect its current descriptor before constructing")
            if current.get("probe_eligible") is not True:
                raise ValueError(f"Capability {identifier} is not currently eligible for a local workflow preview")
            descriptor_hashes[identifier] = current["descriptor_hash"]
        validate_current_options(service, options, [row.capability_id for row in bindings])
        validate_experiment_capabilities(service, [*descriptor_hashes,
            *sorted({"block." + node.type for node in action.graph.nodes})])

        root = service.root(project_id)
        zones = read_zone_state(root)
        zone_nodes = [node for node in action.graph.nodes if node.type == "zone_filter"]
        if zone_nodes and (not zones.confirmed or not zones.zones
                or any(set(node.zone_ids) - {zone.id for zone in zones.zones} for node in zone_nodes)):
            raise ValueError("Draw and confirm the requested regions before previewing this workflow")
        revision_id = uuid.uuid4().hex
        revision_root = task_root / "workflows" / revision_id
        revision_root.mkdir(parents=True, exist_ok=False)
        media = DevelopmentMedia(service, project_id)
        sources, references = _inputs(media, action, revision_root / "media")
        payload["input_refs"] = references
        stage = "composition"
        spec = compose_graph(action.graph, (revision_root / "media").relative_to(root).as_posix(), options)
        if zone_nodes:
            zones_path = revision_root / "zones.json"
            _write(zones_path, _encoded({"zones": [zone.model_dump(mode="json") for zone in zones.zones]}))
            for block in spec.blocks:
                if block.type == "zone_filter":
                    block.params["zones"] = zones_path.relative_to(root).as_posix()
        validate_block_bindings(spec, bindings, 0, options)
        specs = {"spec": spec.model_dump(mode="json", by_alias=True), "options": options.model_dump(mode="json"),
                 "bindings": [row.model_dump(mode="json") for row in bindings]}
        refs = {name: artifacts.write(_encoded(value), "application/json") for name, value in specs.items()}
        payload["artifact_refs"] = [proposal_ref, *refs.values()]
        stage = "compilation"
        compiled = compile_pipeline(spec, root)
        fingerprint = spec_hash(spec, root)
        payload["validated"] = True
        for source in sources:
            # Original source/group tokens are exposed before any model call;
            # run_pipeline additionally records the frozen preview copies.
            media.expose(source, source.image, "investigation_workflow_preview")
        stage = "preview"
        _reserved(store, project_id, task_id, action_id, action)
        payload["executed"] = True
        preview = run_pipeline(spec, root, max_frames=len(action.media_ids))
        preview_ref = artifacts.write(_encoded(preview.model_dump(mode="json")), "application/json")
        payload["preview_artifact"] = preview_ref
        payload["artifact_refs"] = [proposal_ref, *refs.values(), preview_ref]
        if len(preview.frames) != len(sources):
            raise ValueError("Preview did not execute every explicitly selected development image")
        expected_ids = {row.block_id for row in bindings}
        by_block = {row.block_id: row for row in bindings}
        for frame, source, reference in zip(preview.frames, sources, references, strict=True):
            assert isinstance(reference, dict)
            if (frame.image_path != reference["preview_path"] or frame.source_image_sha256 != source.source_sha256
                    or len(frame.inferences) != len(bindings)
                    or {row.block_id for row in frame.inferences} != expected_ids):
                raise ValueError("Preview source or executed inference nodes differ from the saved workflow")
            for inference in frame.inferences:
                identity, binding = inference.result.identity, by_block[inference.block_id]
                if (identity.model_id != binding.model_id or identity.adapter_id != binding.adapter_id
                        or identity.identity_hash != compiled.inference_identities[inference.block_id].identity_hash):
                    raise ValueError("Preview inference identity differs from its captured workflow binding")
            media.resolve(source.media_id, source.source_sha256)
        if spec_hash(spec, root) != fingerprint:
            raise ValueError("Workflow/model identity changed during preview")
        if zone_nodes and read_zone_state(root) != zones:
            raise ValueError("Confirmed region geometry changed during preview")
        validate_current_options(service, options, [row.capability_id for row in bindings])
        _reserved(store, project_id, task_id, action_id, action)
        stage = "receipt"
        limitations: list[JsonValue] = ["Draft preview on selected development images; no measured quality or deployment approval.",
            "Evaluation metric and target are draft assumptions requiring review against the user's objective.",
            "Preview event values are simulated outputs; no events were persisted or dispatched.",
            "The source is a frozen selected-sample set; project-wide use requires explicit rebinding and review."]
        revision = {"schema_version": "a0.workflow.1", "id": revision_id, "project_id": project_id,
            "task_id": task_id, "action_id": action_id, "parent_revision_id": action.parent_revision_id,
            "spec_hash": fingerprint, "preview_spec_hash": fingerprint, "preview_media_ids": list(action.media_ids),
            "input_refs": references, "descriptor_hashes": descriptor_hashes, "evidence_ids": list(action.evidence_ids),
            "artifacts": {**refs, "preview": preview_ref}, "validated": True, "preview_success": True,
            "compiler_warnings": list(compiled.warnings), "limitations": limitations}
        revision_ref = artifacts.write(_encoded(revision), "application/json")
        payload.update(workflow_revision_id=revision_id, spec_hash=fingerprint, preview_spec_hash=fingerprint,
            preview_media_ids=list(action.media_ids), preview_success=True, preview=preview.model_dump(mode="json"),
            model_bindings=[row.model_dump(mode="json") for row in bindings], revision_artifact=revision_ref,
            artifact_refs=[proposal_ref, *refs.values(), preview_ref, revision_ref],
            evaluation_assumption={"metric": spec.eval.metric, "target": spec.eval.target, "review_required": True},
            summary=f"Compiled the proposed workflow and previewed {len(preview.frames)} selected development images. Draft requires review.",
            limitations=limitations, timing={"total_ms": (time.perf_counter() - started) * 1000})
        if len(_encoded(payload)) > 3_500_000:
            raise ValueError("Workflow preview exceeds the bounded observation transport")
        outcome = ToolOutcome(payload=JSON_OBJECT.validate_python(payload))
        _write(revision_root / "version.json", _encoded({**revision, "revision_artifact": revision_ref}))
        return outcome
    except Exception as error:
        detail: dict[str, JsonValue] = {"code": "workflow_failed", "message": str(error)[:1500],
            "retryable": False, "failed_stage": stage}
        for key in ("workflow_revision_id", "preview", "revision_artifact"):
            payload.pop(key, None)
        payload.update(preview_success=False, error=detail,
            summary="Workflow construction did not produce a selectable previewed draft.",
            timing={"total_ms": (time.perf_counter() - started) * 1000})
        if artifacts is not None:
            try:
                diagnostic = artifacts.write(_encoded({"action_id": action_id, "error": detail,
                    "validated": payload["validated"], "executed": payload["executed"]}), "application/json")
                payload["diagnostic_artifact"] = diagnostic
                existing = payload.get("artifact_refs", [])
                payload["artifact_refs"] = [*(existing if isinstance(existing, list) else []), diagnostic]
            except (OSError, ValueError):
                pass  # The typed failure remains available even when evidence storage failed.
        return ToolOutcome(status="failed", payload=JSON_OBJECT.validate_python(payload), error=detail)
