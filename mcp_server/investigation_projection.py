"""Bounded, explicitly partial views of durable investigation evidence."""
from __future__ import annotations

import json

from pydantic import JsonValue

from engine.models.artifacts import canonical_hash
from spec.investigation import (
    ActionReceipt,
    ConstructWorkflow,
    Observation,
    TaskState,
    WorkflowPreviewEvidence,
)

IDENTITY_FIELDS = {"capability_id", "model_id", "adapter_id", "identity_hash", "identity_scope", "provider"}
VALUES_PROJECTION_CHARS = 5000


def selected_workflow_projection(state: TaskState, observations: list[Observation],
                                 actions: list[ActionReceipt]) -> dict[str, JsonValue] | None:
    """Anchor the selected draft to its own saved execution, never a later probe.

    The graph comes from the exact successful construction action. Host source
    rebinding and runtime transforms remain evidenced by its actual preview.
    """
    if state.selected_workflow_revision is None and state.preview_observation_id is None:
        return None
    result: dict[str, JsonValue] = {
        "workflow_revision_id": state.selected_workflow_revision,
        "preview_observation_id": state.preview_observation_id,
        "status": "unavailable",
        "scope": "Selected saved workflow only. Later provisional probes do not change this draft.",
        "context_char_limit": VALUES_PROJECTION_CHARS,
    }
    observation = next((row for row in observations if row.id == state.preview_observation_id), None)
    receipt = next((row for row in actions if observation and row.id == observation.action_id), None)
    if (observation is None or observation.status != "completed" or observation.result_type != "construct_workflow"
            or receipt is None or receipt.status != "completed" or receipt.observation_id != observation.id
            or not isinstance(receipt.action, ConstructWorkflow)):
        result["reason"] = "The selected revision has no matching completed construction and preview receipt."
        return result
    try:
        evidence = WorkflowPreviewEvidence.model_validate({key: value for key, value in observation.payload.items()
                                                          if key in WorkflowPreviewEvidence.model_fields})
    except ValueError:
        result["reason"] = "The saved selected preview is unvalidated or its evidence is inconsistent."
        return result
    if (evidence.workflow_revision_id != state.selected_workflow_revision
            or evidence.preview_media_ids != receipt.action.media_ids or observation.payload.get("executed") is not True):
        result["reason"] = "The saved preview does not match the selected revision, executed status or requested media."
        return result

    graph = receipt.action.graph.model_dump(mode="json")
    nodes: list[JsonValue] = [
        {key: value for key, value in node.model_dump(mode="json").items() if key != "model_reason"}
        for node in receipt.action.graph.nodes
    ]
    applied_graph: dict[str, JsonValue] = {
        "source": "validated_construct_workflow_action", "action_id": receipt.id,
        "graph_sha256": canonical_hash(graph), "nodes": nodes, "total_nodes": len(nodes),
        "metric": receipt.action.graph.metric, "target": receipt.action.graph.target,
    }
    projected = workflow_projection(observation.payload)
    result.update(status="available", preview_status=observation.status,
                  validated=True, preview_success=True, executed=True,
                  spec_hash=evidence.spec_hash, preview_spec_hash=evidence.preview_spec_hash,
                  preview_media_ids=list(evidence.preview_media_ids), preview=projected["preview"],
                  applied_graph=applied_graph, projection_note=projected["projection_note"],
                  retrieve_saved_values={"type": "inspect_observation", "observation_id": observation.id,
                                         "view": "values", "limit": 5, "cursor": None})
    # Omit whole structures, never shorten a text reading into a different value.
    # Every fallback retains the same preview ID and exact revision/hash binding.
    if len(json.dumps(result, ensure_ascii=False)) > VALUES_PROJECTION_CHARS:
        applied_graph.pop("nodes")
        applied_graph.update(nodes_omitted_for_size=True,
                             source_note="Exact graph remains in this saved construction action; the draft is unchanged.")
    if len(json.dumps(result, ensure_ascii=False)) > VALUES_PROJECTION_CHARS:
        preview = result["preview"]
        assert isinstance(preview, dict)
        result["preview"] = {
            "frames": [], "frames_page": {"total_items": len(evidence.preview.frames), "returned_items": 0,
                                           "truncated": True, "omitted_for_size": True},
        }
        result["projection_note"] = "Selected preview values and metadata exceed the context budget and are omitted. Use retrieve_saved_values; the complete immutable receipt is unchanged."
    return result


def _page(row: dict[str, JsonValue], key: str, limit: int) -> None:
    values = row.get(key)
    if isinstance(values, list):
        row[key] = values[:limit]
        if len(values) > limit:
            row[f"{key}_page"] = {"total_items": len(values), "returned_items": limit, "truncated": True}


def compact_identity(value: JsonValue) -> JsonValue:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if key in IDENTITY_FIELDS}


def compact_geometry(value: JsonValue, *, source_only: bool = False) -> JsonValue:
    if not isinstance(value, dict):
        return value
    result = {key: item for key, item in value.items() if key not in {"polygon", "source_polygon"}}
    if source_only and result.get("source_box") is not None:
        result.pop("box", None)
    for key in ("box", "source_box"):
        box = result.get(key)
        if isinstance(box, list):
            result[key] = [round(item, 6) if isinstance(item, float) else item for item in box]
    return result


def probe_projection(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Expose readings and source geometry, without repeated binary references."""
    omitted = {"artifact_refs", "image_artifact", "overlay_artifact", "result_artifact"}
    result = {key: value for key, value in payload.items() if key not in omitted}
    identities = result.get("identity_refs")
    if isinstance(identities, list):
        result["identity_refs"] = [compact_identity(item) for item in identities]
    items = result.get("items")
    if isinstance(items, list):
        selected = [compact_geometry(item, source_only=True) for item in items[:20]]
        result["items"] = selected
        result["returned_items"] = len(selected)
        result["projection_note"] = ("Up to twenty actual values; normalized source_box rounded to six decimals. "
                                     "Polygons and verbose artifact/identity fields omitted. Follow retrieve_saved_values "
                                     "when present; full evidence remains available through inspect_observation.")
        while selected and len(json.dumps(result, ensure_ascii=False)) > VALUES_PROJECTION_CHARS:
            selected.pop()
            result["returned_items"] = len(selected)
        if len(selected) < len(items):
            result["truncated"] = True
            # A source cursor after 20 would skip values omitted by this view.
            result["next_cursor"] = None
    return result


def bounded_values_projection(payload: dict[str, JsonValue], original: dict[str, JsonValue], *,
                              observation_id: str, inspection: bool) -> dict[str, JsonValue]:
    """Budget the complete view, including a correctly scoped continuation action.

    A clipped inspection page restarts its original source cursor with a smaller
    limit, rather than skipping hidden values or repeating the oversized request.
    Whole readings are omitted, never shortened to fit this context projection.
    """
    result = payload.copy()
    source_id = original.get("observation_id") if inspection else observation_id
    if not isinstance(source_id, str):
        source_id = observation_id
    view = original.get("view", "values") if inspection else "values"
    if not isinstance(view, str) or view not in {"values", "geometry", "image", "overlay", "error"}:
        view = "values"
    restart_cursor = original.get("source_cursor") if inspection else None
    items, original_items = result.get("items"), original.get("items")
    selected = list(items) if isinstance(items, list) else []
    if isinstance(items, list):
        result["items"] = selected
    clipped = isinstance(original_items, list) and len(selected) < len(original_items)

    def continuation() -> None:
        if clipped:
            result.update(truncated=True, next_cursor=None, returned_items=len(selected), omitted_for_size=True)
            if inspection and isinstance(original_items, list) and len(original_items) == 1 and not selected:
                # Even a one-row request cannot advance through this projection.
                # Do not suggest the identical action as a way to recover it.
                result.update(unprojectable=True,
                              projection_note="The single-row page exceeds the context size budget. "
                                              "It cannot be exposed completely in this text projection; "
                                              "the full saved receipt is unchanged.")
                result.pop("retrieve_saved_values", None)
                return
        if result.get("truncated") is True:
            result["retrieve_saved_values"] = {
                "type": "inspect_observation", "observation_id": source_id, "view": view,
                "limit": max(1, len(selected)) if clipped else 5,
                "cursor": restart_cursor if clipped else original.get("next_cursor"),
            }

    continuation()
    while selected and len(json.dumps(result, ensure_ascii=False)) > VALUES_PROJECTION_CHARS:
        selected.pop()
        clipped = True
        continuation()
    if len(json.dumps(result, ensure_ascii=False)) > VALUES_PROJECTION_CHARS:
        # Even zero values can exceed the budget (for example, long adapter
        # warnings). Preserve bounded authority fields and explicitly omit the
        # metadata; the durable receipt/artifact is never changed.
        authority = {"executed", "execution_status", "observation_id", "source_result_type", "source_status",
                     "view", "source_cursor", "total_items", "workflow_revision_id", "spec_hash", "preview_spec_hash"}
        result = {key: value for key, value in result.items() if key in authority
                  and (value is None or isinstance(value, (bool, int, float))
                       or isinstance(value, str) and len(value) <= 256)}
        selected = []
        clipped = True
        result.update(items=[], omitted_for_size=True,
                      projection_note="Metadata and values omitted to fit the 5000-character context budget. "
                                      "Full receipt remains saved; retrieve_saved_values restarts the original page.")
        continuation()
    return result


def workflow_projection(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Keep exact draft authority and a small actual preview, with retrievable omissions.

    This is a projection, never a replacement RunResult or a correctness verdict.
    The complete immutable result remains in the task and inspect_observation.
    """
    keep = {"executed", "validated", "preview_success", "workflow_revision_id", "spec_hash",
            "preview_spec_hash", "preview_media_ids", "summary", "limitations", "timing"}
    result = {key: value for key, value in payload.items() if key in keep}
    preview = payload.get("preview")
    if not isinstance(preview, dict):
        return payload
    frames = preview.get("frames")
    frames = frames if isinstance(frames, list) else []
    selected: list[JsonValue] = []
    # One frame is sufficient as an automatic sample, not as proof for other frames.
    for frame in frames[:1]:
        if not isinstance(frame, dict):
            continue
        item = {key: value for key, value in frame.items() if key != "image_path"}
        for key in ("detections", "texts", "events", "judgements", "comparisons"):
            _page(item, key, 5)
        detections = item.get("detections")
        if isinstance(detections, list):
            item["detections"] = [compact_geometry(value) for value in detections]
        inferences = item.get("inferences")
        if isinstance(inferences, list):
            compact: list[JsonValue] = []
            for inference in inferences[:2]:
                if not isinstance(inference, dict):
                    continue
                inference = inference.copy()
                values = inference.get("result")
                if isinstance(values, dict):
                    values = values.copy()
                    values["identity"] = compact_identity(values.get("identity"))
                    _page(values, "readings", 5)
                    _page(values, "detections", 5)
                    for key in ("readings", "detections"):
                        rows = values.get(key)
                        if isinstance(rows, list):
                            values[key] = [compact_geometry(value) for value in rows]
                    inference["result"] = values
                compact.append(inference)
            item["inferences"] = compact
            if len(inferences) > 2:
                item["inferences_page"] = {"total_items": len(inferences), "returned_items": 2, "truncated": True}
        selected.append(item)
    # Unbounded text or polygon detail must not defeat the prompt budget. Retain
    # identity/size rather than silently clipping text into a different reading.
    omitted_for_size = len(json.dumps(selected, ensure_ascii=False)) > 5500
    if omitted_for_size:
        selected = []
    result["preview"] = {"frames": selected, "elapsed_s": preview.get("elapsed_s"),
                         "warnings": preview.get("warnings", []),
                         "frames_page": {"total_items": len(frames), "returned_items": len(selected),
                                         "truncated": len(selected) < len(frames),
                                         "omitted_for_size": omitted_for_size}}
    result["projection_note"] = ("Partial preview: sample frame, at most two inference blocks and five values per list; "
                                 "boxes rounded to six decimals; polygons, paths and verbose identities omitted. Use inspect_observation(values/geometry) "
                                 "from cursor null for complete paged evidence. No inference was rerun.")
    return result
