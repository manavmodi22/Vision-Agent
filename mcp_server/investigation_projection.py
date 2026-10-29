"""Bounded, explicitly partial views of durable investigation evidence."""
from __future__ import annotations

import json

from pydantic import JsonValue

IDENTITY_FIELDS = {"capability_id", "model_id", "adapter_id", "identity_hash", "identity_scope", "provider"}


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
        result["items"] = [compact_geometry(item, source_only=True) for item in items[:5]]
        result["returned_items"] = min(len(items), 5)
        if len(items) > 5:
            result["truncated"] = True
            result["next_cursor"] = None
    result["projection_note"] = ("First five actual values; normalized source_box rounded to six decimals. "
                                 "Polygons and verbose artifact/identity fields omitted. Use inspect_observation "
                                 "from cursor null for full paged values/geometry or image/overlay references.")
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
