"""Projection regressions; synthetic saved values, no inference or external model calls."""
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from engine.investigations.probes import Artifacts
from engine.investigations.store import InvestigationStore
from engine.investigations.tools import InvestigationTools
from engine.service import WorkspaceService
from mcp_server.investigations import observation_projection
from spec.investigation import NextAction, Observation


@pytest.mark.parametrize("view", ["values", "geometry"])
def test_retrieval_hint_pages_original_immutable_observation_in_same_view(tmp_path: Path, view: str) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Saved-observation paging software test", "custom")
    store = InvestigationStore(service)
    task = store.create(project.id, "Exercise saved evidence paging; no real inference")
    tools = InvestigationTools(service, store)

    def reserve(action: dict[str, Any]) -> Any:
        decision = NextAction.model_validate({"state_revision": store.get(project.id, task.id).revision,
            "decision_summary": "Scripted paging test; no language model", "action": action})
        call = store.start_model_call(project.id, task.id, {}, "scripted-paging-test")
        store.finish_model_call(project.id, task.id, call.id, {"decision": decision.model_dump(mode="json")})
        return store.reserve_action(project.id, task.id, decision)

    def inspect(action: dict[str, Any]) -> Observation:
        receipt = reserve(action)
        result = tools.execute(project.id, task.id, receipt.id, receipt.action)
        saved = store.complete_action(project.id, task.id, receipt.id, result.payload,
                                      status=result.status, error=result.error)
        assert saved.status == "completed", saved.error
        return saved

    # Save deterministic test rows in the same content-addressed artifact format
    # the real probe reader uses. No adapter is invoked and executed stays false.
    items = [{"item_id": f"software-row-{index}", "text": f"Literal-{index:03}",
              "kind": "ocr", "box": [.1, .2, .3, .4], "source_box": [.6, .2, .8, .4],
              "source_polygon": [[.6, .2], [.8, .2], [.8, .4], [.6, .4]]}
             for index in range(12)]
    artifacts = Artifacts(store.root(project.id, task.id))
    artifact_bytes = json.dumps({"software_fixture": True, "items": items}, sort_keys=True).encode()
    reference = artifacts.write(artifact_bytes, "application/json")
    receipt = reserve({"type": "run_probe", "capability_id": "model.apple-vision",
        "inspected_descriptor_hash": "c" * 64, "media_id": "software-fixture", "source_sha256": "d" * 64,
        "request": {"task": "ocr", "model_id": "apple-vision"}})
    source = store.complete_action(project.id, task.id, receipt.id, {
        "executed": False, "software_fixture": True, "input_refs": [], "result_artifact": reference,
        "items": items, "total_items": 12, "returned_items": 12, "truncated": False, "next_cursor": None})
    original = source.model_dump(mode="json")
    page = inspect({"type": "inspect_observation", "observation_id": source.id,
                    "view": view, "limit": 5, "cursor": None})
    collected = list(page.payload["items"])
    for expected_start in (5, 10):
        before = page.model_dump(mode="json")
        hint = observation_projection(page)["payload"]["retrieve_saved_values"]
        next_page = inspect(hint)
        # Follow the actual supplied action before checking it: the broken hint
        # succeeds but silently pages the five-row inspection receipt itself.
        assert next_page.payload["total_items"] == 12, (
            f"Hint inspected a nested page instead of all original rows: {hint}; "
            f"reported total={next_page.payload['total_items']}")
        assert hint["observation_id"] == source.id
        assert hint["view"] == view
        assert hint["cursor"] == page.payload["next_cursor"]
        assert next_page.payload["observation_id"] == source.id
        assert next_page.payload["source_result_type"] == "run_probe"
        assert [row["item_id"] for row in next_page.payload["items"]] == [
            f"software-row-{i}" for i in range(expected_start, min(expected_start + 5, 12))]
        assert page.model_dump(mode="json") == before
        collected.extend(next_page.payload["items"])
        page = next_page
    assert [row["item_id"] for row in collected] == [row["item_id"] for row in items]
    assert page.payload["truncated"] is False and page.payload["next_cursor"] is None
    if view == "values":
        assert [row["text"] for row in collected] == [row["text"] for row in items]
    else:
        assert all("text" not in row and row["source_box"] == [.6, .2, .8, .4] for row in collected)
    assert store.get_observation(project.id, task.id, source.id).model_dump(mode="json") == original
    assert artifacts.read(reference) == artifact_bytes


def test_complete_probe_payload_including_retrieval_hint_stays_within_5000_chars() -> None:
    payload = {"executed": True, "items": [
        {"text": "X" * 1327, "kind": "ocr", "item_id": f"probe:{i}",
         "identity_scope": "frame_local_observation", "confidence": 1.0, "source_box": [.1, .2, .3, .4]}
        for i in range(4)], "total_items": 4, "returned_items": 4, "truncated": False, "next_cursor": None}
    observation = Observation(id="a" * 32, action_id="b" * 32, result_type="run_probe", status="completed",
                              payload=payload, created_at="2026-10-29T00:00:00Z")
    before = deepcopy(observation.model_dump(mode="json"))
    projected = observation_projection(observation)["payload"]
    assert observation.model_dump(mode="json") == before
    assert projected["truncated"] is True and projected["returned_items"] < 4
    assert projected["retrieve_saved_values"]["observation_id"] == observation.id
    assert all(row["text"] == "X" * 1327 for row in projected["items"])
    size = len(json.dumps(projected, ensure_ascii=False))
    assert size <= 5000, f"Complete model-visible payload is {size} chars after retrieval hint was added"


def test_metadata_only_oversize_uses_explicit_bounded_fallback_without_receipt_mutation() -> None:
    # Six 1000-character warnings are within the existing InferenceResult bounds.
    payload = {"executed": True, "execution_status": "completed", "items": [{"text": "ACTUAL-LITERAL"}],
               "warnings": [f"{i}:" + "W" * 998 for i in range(6)],
               "total_items": 1, "returned_items": 1, "truncated": False, "next_cursor": None}
    observation = Observation(id="c" * 32, action_id="d" * 32, result_type="run_probe", status="completed",
                              payload=payload, created_at="2026-10-29T00:00:00Z")
    before = deepcopy(observation.model_dump(mode="json"))
    projected = observation_projection(observation)["payload"]
    assert observation.model_dump(mode="json") == before
    size = len(json.dumps(projected, ensure_ascii=False))
    assert size <= 5000, f"Metadata alone defeats the declared projection limit: {size} chars"
    assert projected["executed"] is True and projected["total_items"] == 1
    assert projected["items"] == [] and projected["returned_items"] == 0
    assert projected["truncated"] is True and projected["next_cursor"] is None
    assert projected.get("omitted_for_size") is True
    assert projected["retrieve_saved_values"] == {"type": "inspect_observation", "observation_id": observation.id,
                                                "view": "values", "limit": 1, "cursor": None}


@pytest.mark.parametrize("view", ["values", "geometry"])
def test_clipped_inspection_page_restarts_its_original_cursor_without_skipping(view: str) -> None:
    polygon = [[.2 + .1 * math.cos(2 * math.pi * i / 256), .3 + .1 * math.sin(2 * math.pi * i / 256)]
               for i in range(256)]
    items = [{"item_id": f"original-{i}", "source_box": [.1, .2, .3, .4],
              **({"text": "Literal" * 200} if view == "values" else
                 {"source_polygon": polygon})} for i in range(8)]
    payload = {"executed": False, "observation_id": "a" * 32, "source_result_type": "run_probe",
               "view": view, "source_cursor": "0123456789abcdef:10", "items": items,
               "total_items": 30, "returned_items": 8, "truncated": True, "next_cursor": "0123456789abcdef:18"}
    observation = Observation(id="b" * 32, action_id="c" * 32, result_type="inspect_observation", status="completed",
                              payload=payload, created_at="2026-10-29T00:00:00Z")
    before = deepcopy(observation.model_dump(mode="json"))
    projected = observation_projection(observation)["payload"]
    assert len(json.dumps(projected, ensure_ascii=False)) <= 5000
    assert projected["returned_items"] < 8 and projected["truncated"] is True
    assert projected["next_cursor"] is None
    assert projected["retrieve_saved_values"] == {"type": "inspect_observation", "observation_id": "a" * 32,
                                                "view": view, "limit": max(1, projected["returned_items"]),
                                                "cursor": "0123456789abcdef:10"}
    assert observation.model_dump(mode="json") == before


def test_size_clipped_retrieval_hints_eventually_reach_every_exact_long_reading(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Long saved-readings paging software test", "custom")
    store = InvestigationStore(service)
    task = store.create(project.id, "Page deterministic saved evidence without inference")
    tools = InvestigationTools(service, store)

    def reserve(action: dict[str, Any]) -> Any:
        decision = NextAction.model_validate({"state_revision": store.get(project.id, task.id).revision,
            "decision_summary": "Scripted paging test; no language model", "action": action})
        call = store.start_model_call(project.id, task.id, {}, "scripted-long-readings-test")
        store.finish_model_call(project.id, task.id, call.id, {"decision": decision.model_dump(mode="json")})
        return store.reserve_action(project.id, task.id, decision)

    items = [{"item_id": f"long-{index}", "text": f"Literal-{index:03}: " + "É" * 1987,
              "kind": "ocr", "source_box": [.1, .2, .3, .4]} for index in range(12)]
    artifacts = Artifacts(store.root(project.id, task.id))
    artifact_bytes = json.dumps({"software_fixture": True, "items": items}, sort_keys=True).encode()
    reference = artifacts.write(artifact_bytes, "application/json")
    receipt = reserve({"type": "run_probe", "capability_id": "model.apple-vision",
        "inspected_descriptor_hash": "c" * 64, "media_id": "software-fixture", "source_sha256": "d" * 64,
        "request": {"task": "ocr", "model_id": "apple-vision"}})
    source = store.complete_action(project.id, task.id, receipt.id, {
        "executed": False, "software_fixture": True, "input_refs": [], "result_artifact": reference,
        "items": items, "total_items": len(items), "returned_items": len(items), "truncated": False,
        "next_cursor": None})
    original = source.model_dump(mode="json")
    action = {"type": "inspect_observation", "observation_id": source.id,
              "view": "values", "limit": 5, "cursor": None}
    requested: set[str] = set()
    collected: dict[str, dict[str, Any]] = {}
    for _ in range(14):
        signature = json.dumps(action, sort_keys=True)
        assert signature not in requested, "Clipped-page retrieval repeats the same request without advancing"
        requested.add(signature)
        receipt = reserve(action)
        result = tools.execute(project.id, task.id, receipt.id, receipt.action)
        page = store.complete_action(project.id, task.id, receipt.id, result.payload,
                                     status=result.status, error=result.error)
        assert page.status == "completed", page.error
        before = page.model_dump(mode="json")
        projected = observation_projection(page)["payload"]
        assert len(json.dumps(projected, ensure_ascii=False)) <= 5000
        assert projected["total_items"] == len(items)
        for row in projected["items"]:
            collected[row["item_id"]] = row
        assert page.model_dump(mode="json") == before
        if not projected["truncated"]:
            break
        action = projected["retrieve_saved_values"]
        assert action["observation_id"] == source.id and action["view"] == "values"
    else:
        pytest.fail("Retrieval did not terminate within the bounded number of source pages")
    assert list(collected) == [row["item_id"] for row in items]
    assert [row["text"] for row in collected.values()] == [row["text"] for row in items]
    assert store.get_observation(project.id, task.id, source.id).model_dump(mode="json") == original
    assert artifacts.read(reference) == artifact_bytes


def test_single_oversize_inspection_row_is_explicitly_unprojectable_and_never_complete() -> None:
    polygon = [[.2 + .1 * math.cos(2 * math.pi * i / 256), .3 + .1 * math.sin(2 * math.pi * i / 256)]
               for i in range(256)]
    payload = {"executed": False, "observation_id": "a" * 32, "source_result_type": "run_probe",
               "view": "geometry", "source_cursor": None,
               "items": [{"item_id": "large-geometry", "source_polygon": polygon}],
               "total_items": 1, "returned_items": 1, "truncated": False, "next_cursor": None}
    observation = Observation(id="b" * 32, action_id="c" * 32, result_type="inspect_observation",
                              status="completed", payload=payload, created_at="2026-10-29T00:00:00Z")
    before = deepcopy(observation.model_dump(mode="json"))
    projected = observation_projection(observation)["payload"]
    assert projected["items"] == [] and projected["returned_items"] == 0
    assert projected["total_items"] == 1 and projected["truncated"] is True
    assert projected["next_cursor"] is None
    assert projected.get("omitted_for_size") is True
    assert projected.get("unprojectable") is True
    assert "retrieve_saved_values" not in projected
    assert "size" in projected.get("projection_note", "").lower()
    assert len(json.dumps(projected, ensure_ascii=False)) <= 5000
    assert observation.model_dump(mode="json") == before
