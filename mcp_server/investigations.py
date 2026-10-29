"""Separate durable authority for model-selected provisional investigations."""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import Counter

from filelock import FileLock
from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue

from engine.investigations.media import DevelopmentMedia
from engine.investigations.probes import JSON_OBJECT
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.investigations.tools import InvestigationTools, ToolOutcome, _page
from engine.investigations.worker import run_owned_probe
from engine.models.artifacts import canonical_hash
from mcp_server.investigation_projection import (
    compact_identity,
    probe_projection,
    workflow_projection,
)
from spec.investigation import (
    ActionReceipt,
    BuilderDecision,
    ConstructWorkflow,
    ModelCall,
    Observation,
    RunProbe,
    TaskState,
)


def observation_projection(observation: Observation) -> dict[str, JsonValue]:
    """Keep values and authority fields typed; bulky detail stays in the ledger."""
    row = observation.model_dump(mode="json")
    payload = observation.payload.copy()
    if observation.result_type == "construct_workflow" and isinstance(payload.get("preview"), dict):
        payload = workflow_projection(payload)
    elif observation.result_type == "run_probe":
        payload = probe_projection(payload)
    if isinstance(payload.get("model_view"), dict):
        payload = {"descriptor": payload["model_view"], "full_descriptor_omitted": True}
    if len(json.dumps(payload, ensure_ascii=False)) > 5000:
        identity = payload.get("identity")
        if isinstance(identity, dict):
            payload["identity"] = compact_identity(identity)
        items = payload.get("items")
        if isinstance(items, list) and len(items) > 5:
            payload["items"] = items[:5]
            payload["returned_items"] = 5
            payload["truncated"] = True
            payload.pop("next_cursor", None)
        payload["projection_note"] = "Bounded context projection; inspect_observation from cursor null for full paged values/geometry."
    row["payload"] = payload
    return row


def recent_action_context(actions: list[ActionReceipt]) -> list[JsonValue]:
    """Expose actual selected arguments and repetition, not only the model's prose."""
    arguments = [item.action.model_dump(mode="json") for item in actions]
    signatures = [canonical_hash(value) for value in arguments]
    occurrences = Counter(signatures)
    rows: list[JsonValue] = []
    for item, original, signature in zip(actions[-4:], arguments[-4:], signatures[-4:], strict=True):
        selected = original.copy()
        selected.pop("type")
        graph = selected.pop("graph", None)
        if graph is not None:
            selected.update(graph_omitted=True, graph_sha256=canonical_hash(graph))
        if len(json.dumps(selected, ensure_ascii=False)) > 2000:
            selected = {"arguments_omitted_for_size": True}
        rows.append({"id": item.id, "type": item.action.type, "arguments": selected,
                     "arguments_sha256": signature,
                     "same_arguments_attempts_in_task": occurrences[signature],
                     "purpose": item.decision.decision_summary,
                     "based_on_observation_ids": list(item.decision.based_on_observation_ids),
                     "observation_id": item.observation_id, "status": item.status})
    return rows


def investigation_context(store: InvestigationStore, project_id: str, task_id: str) -> dict[str, JsonValue]:
    state = store.get(project_id, task_id)
    observations = store.observations(project_id, task_id)
    actions = store.actions(project_id, task_id)
    calls = store.model_calls(project_id, task_id)
    known_capabilities: dict[str, JsonValue] = {}
    for observation in observations:
        view = observation.payload.get("model_view")
        if isinstance(view, dict) and isinstance(view.get("id"), str):
            identifier = str(view["id"])
            known_capabilities.pop(identifier, None)
            known_capabilities[identifier] = {key: value for key, value in view.items()
                if key in {"id", "descriptor_hash", "probe_eligible", "probe_tasks", "class_vocabulary", "project_eligibility"}}
    projected: list[JsonValue] = []
    visible: list[str] = []
    seen_metadata: set[str] = set()
    # Deduplicate before applying the three-observation bound: repeated metadata
    # must not evict a distinct actual probe and its geometry from the next call.
    for observation in reversed(observations):
        projection = observation_projection(observation)
        if observation.status == "completed" and observation.result_type in {
            "discover_capabilities", "inspect_capability", "inspect_media"
        }:
            signature = json.dumps({"type": observation.result_type, "payload": projection["payload"]}, sort_keys=True)
            if signature in seen_metadata:
                continue
            seen_metadata.add(signature)
        projected.insert(0, projection)
        visible.insert(0, observation.id)
        if len(projected) == 3:
            break
    return {
        "state": state.model_dump(mode="json"),
        "observations": projected,
        "visible_observation_ids": [identifier for identifier in visible],
        "earlier_observations": [{"id": item.id, "result_type": item.result_type, "status": item.status}
                                 for item in observations if item.id not in visible],
        "recent_actions": recent_action_context(actions),
        "last_model_error": calls[-1].error[:1500] if calls and calls[-1].error else None,
        "inspected_capabilities": list(known_capabilities.values())[-4:],
        "context_note": "The latest three distinct observations are supplied; identical metadata uses its newest receipt. Recent actions include actual arguments and attempt counts. Their purpose text is the model's earlier interpretation, not new tool evidence. Full history remains inspectable.",
        "development_media": development_media_summary(store, project_id),
        "planner_modality": "text_only; image paths are references, not supplied image pixels",
    }


def development_media_summary(store: InvestigationStore, project_id: str) -> dict[str, JsonValue]:
    """Initial input metadata is context, not a host-selected experiment or pixels."""
    media = DevelopmentMedia(store.service, project_id)
    rows: list[JsonValue] = []
    unavailable: list[JsonValue] = []
    try:
        selected, counts = _page(media.identifiers(), None, 3, "media")
        for identifier in selected:
            try:
                rows.append(JSON_OBJECT.validate_python(media.resolve(identifier).metadata()))
            except (ValueError, OSError) as error:
                unavailable.append({"media_id": identifier, "error": str(error)[:500]})
    except (ValueError, OSError) as error:
        return {"items": [], "error": str(error)[:500], "pixels_visible_to_planner": False}
    return {**counts, "items": rows, "returned_items": len(rows), "unavailable": unavailable,
            "pixels_visible_to_planner": False,
            "scope": "Current development input metadata only. Use these exact IDs and source hashes. "
                     "inspect_media can page the inventory; no pixels or inference were supplied here."}


async def execute_step(store: InvestigationStore, project_id: str, task_id: str,
                       decision: BuilderDecision) -> Observation:
    # Cross-process serialization covers reservation, the external worker and commit.
    # A persisted unknown reservation is never an invitation to execute again.
    with FileLock(store.root(project_id, task_id) / ".dispatch.lock", timeout=0):
        calls = store.model_calls(project_id, task_id)
        for prior in store.actions(project_id, task_id):
            if calls and prior.model_call_id == calls[-1].id and prior.decision == decision:
                if prior.observation_id:
                    return store.get_observation(project_id, task_id, prior.observation_id)
                raise InvestigationConflict("This action was already reserved; reconcile interruption before a new attempt")
        receipt = store.reserve_action(project_id, task_id, decision)
        try:
            action = receipt.action
            if action.type in {"ask_user", "finish", "prepare_workflow"}:
                outcome = ToolOutcome(payload={"selected_action": action.model_dump(mode="json"),
                                               "executed": False})
            elif isinstance(action, (RunProbe, ConstructWorkflow)):
                task = store.get(project_id, task_id)
                remaining = task.budget.max_elapsed_s - task.budget.elapsed_s
                raw = await run_owned_probe(store.service.repository.root, project_id, task_id,
                                            receipt.id, action, max(.01, min(90, remaining)))
                outcome = ToolOutcome.model_validate(raw)
            else:
                outcome = await asyncio.to_thread(
                    InvestigationTools(store.service, store).execute, project_id, task_id, receipt.id, action)
        except asyncio.CancelledError:
            with contextlib.suppress(InvestigationConflict):
                store.complete_action(project_id, task_id, receipt.id, {}, status="interrupted",
                                      error="Investigation action cancelled; uncommitted results discarded")
            raise
        except Exception as error:
            outcome = ToolOutcome(status="failed", payload={"executed": None},
                                  error={"code": type(error).__name__, "message": str(error),
                                         "execution_status": "unknown_or_incomplete"})
        return store.complete_action(project_id, task_id, receipt.id, outcome.payload,
                                     status=outcome.status, error=outcome.error)


def register_investigation_tools(server: FastMCP[None], store: InvestigationStore) -> None:
    @server.tool()
    def investigation_context_read(project_id: str, task_id: str) -> dict[str, JsonValue]:
        """Load bounded persisted state and actual observations; no strategy selected by host."""
        return investigation_context(store, project_id, task_id)

    @server.tool()
    def investigation_model_start(project_id: str, task_id: str,
                                  context: dict[str, JsonValue], model: str) -> ModelCall:
        """Reserve and capture a real model request before sending it."""
        inner = context.get("context")
        visible = inner.get("visible_observation_ids", []) if isinstance(inner, dict) else []
        if not isinstance(visible, list) or not all(isinstance(item, str) for item in visible):
            raise ValueError("Model-visible observation IDs must be a string list")
        return store.start_model_call(project_id, task_id, context, model,
                                      visible_observation_ids=[str(item) for item in visible])

    @server.tool()
    def investigation_model_finish(project_id: str, task_id: str, call_id: str,
                                   response: dict[str, JsonValue] | None = None,
                                   error: str | None = None) -> ModelCall:
        """Persist the actual model response or failure without executing it."""
        return store.finish_model_call(project_id, task_id, call_id, response, error)

    @server.tool()
    async def investigation_step(project_id: str, task_id: str, decision: BuilderDecision) -> Observation:
        """Reserve, execute and persist exactly one captured model-selected action."""
        return await execute_step(store, project_id, task_id, decision)

    @server.tool()
    def investigation_stop(project_id: str, task_id: str, reason: str) -> TaskState:
        """Stop an investigation inconclusively; never approve or claim a ready application."""
        return store.stop(project_id, task_id, reason, status="inconclusive")
