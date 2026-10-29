"""Scripted protocol receipts test draft/experiment separation, not model accuracy."""
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from agent.investigation import SYSTEM
from engine.investigations.store import InvestigationStore
from engine.service import WorkspaceService
from mcp_server.investigation_projection import selected_workflow_projection
from mcp_server.investigations import investigation_context
from spec.authoring import MatchNode
from spec.investigation import BuilderDecision


def complete(store: InvestigationStore, project_id: str, task_id: str,
             action: dict[str, Any], payload: dict[str, Any]) -> Any:
    state = store.get(project_id, task_id)
    decision = TypeAdapter(BuilderDecision).validate_python({
        "type": "workflow_decision" if action["type"] == "construct_workflow" else "next_action",
        "state_revision": state.revision, "decision_summary": "Scripted protocol fixture",
        "action": action,
    })
    call = store.start_model_call(project_id, task_id, {}, "scripted-test")
    store.finish_model_call(project_id, task_id, call.id, decision.model_dump(mode="json"))
    receipt = store.reserve_action(project_id, task_id, decision)
    result = store.complete_action(project_id, task_id, receipt.id, payload)
    assert result.status == "completed", result.error
    return result


def workflow(store: InvestigationStore, project_id: str, task_id: str,
             revision: str = "a" * 32, texts: list[str] | None = None) -> Any:
    complete(store, project_id, task_id, {"type": "prepare_workflow", "summary": "Load schema"}, {})
    return complete(store, project_id, task_id, {
        "type": "construct_workflow", "media_ids": ["media-scripted"],
        "graph": {"name": "Scripted saved draft", "metric": "text_accuracy", "target": 1,
                  "nodes": [{"type": "frame_sample", "id": "sample", "fps": 2},
                            {"type": "ocr", "id": "reader", "image": "$sample.frame",
                             "model_capability_id": "model.apple-vision", "model_reason": "Scripted choice"}]}}, {
        "executed": True, "validated": True, "preview_success": True,
        "workflow_revision_id": revision, "spec_hash": "b" * 64, "preview_spec_hash": "b" * 64,
        "preview_media_ids": ["media-scripted"],
        "preview": {"frames": [{"image_path": "/scripted/fixture.png", "source_image_sha256": "c" * 64,
                                "texts": texts or ["Heading", "Raw-4817", "Footer", "Other-552"]}],
                    "elapsed_s": .1, "warnings": []},
    })


@pytest.fixture
def selected(tmp_path: Path) -> Any:
    service = WorkspaceService(tmp_path / "workspace")
    project_id = service.create_project("Selected context protocol test", "custom").id
    store = InvestigationStore(service)
    task_id = store.create(project_id, "Build the requested application").id
    observation = workflow(store, project_id, task_id)
    return store, project_id, task_id, observation


def test_selected_actual_preview_survives_later_successful_probes_and_records_exposure(selected: Any) -> None:
    store, project_id, task_id, saved = selected
    probes = []
    for _ in range(4):
        probes.append(complete(store, project_id, task_id, {
            "type": "run_probe", "capability_id": "model.apple-vision", "inspected_descriptor_hash": "d" * 64,
            "media_id": "media-scripted", "source_sha256": "c" * 64,
            "transforms": [{"type": "crop", "box": [.2, .2, .8, .5]}],
            "request": {"task": "ocr", "model_id": "apple-vision"}},
            {"executed": True, "items": [{"text": "Raw-4817", "source_box": [.2, .2, .8, .5]}]}))
    path = store.root(project_id, task_id) / "task.json"
    before = path.read_bytes()
    context = investigation_context(store, project_id, task_id)
    anchor = context["selected_workflow"]
    assert anchor["workflow_revision_id"] == saved.payload["workflow_revision_id"]
    assert anchor["preview_observation_id"] == saved.id
    assert anchor["preview"]["frames"][0]["texts"] == saved.payload["preview"]["frames"][0]["texts"]
    assert anchor["applied_graph"]["nodes"][1]["image"] == "$sample.frame"
    assert [row["id"] for row in context["observations"]] == [row.id for row in probes[-3:]]
    assert saved.id in context["visible_observation_ids"] and saved.id in context["citable_observation_ids"]
    assert saved.id not in {row["id"] for row in context["earlier_observations"]}
    assert path.read_bytes() == before
    call = store.start_model_call(project_id, task_id, {"context": context}, "scripted-test",
                                  visible_observation_ids=context["visible_observation_ids"])
    assert saved.id in call.visible_observation_ids
    assert "Successful provisional probes do not change the saved workflow" in SYSTEM


def test_selected_revision_changes_only_with_saved_construction_and_is_not_duplicated(selected: Any) -> None:
    store, project_id, task_id, old = selected
    new = workflow(store, project_id, task_id, "e" * 32, ["A new exact reading\nwith spacing  "])
    context = investigation_context(store, project_id, task_id)
    anchor = context["selected_workflow"]
    assert anchor["workflow_revision_id"] == "e" * 32 and anchor["preview_observation_id"] == new.id
    assert anchor["preview"]["frames"][0]["texts"] == ["A new exact reading\nwith spacing  "]
    assert anchor["applied_graph"]["action_id"] == new.action_id
    assert anchor["preview_observation_id"] != old.id
    assert new.id not in {row["id"] for row in context["observations"]}
    assert context["visible_observation_ids"].count(new.id) == 1


@pytest.mark.parametrize("defect", ["missing", "revision", "hash", "unvalidated", "failed", "action", "media", "unexecuted"])
def test_missing_or_inconsistent_selected_preview_never_substitutes_other_evidence(selected: Any, defect: str) -> None:
    store, project_id, task_id, _ = selected
    state = store.get(project_id, task_id)
    observations = copy.deepcopy(store.observations(project_id, task_id))
    actions = copy.deepcopy(store.actions(project_id, task_id))
    observation = observations[-1]
    if defect == "missing":
        observations.pop()
    elif defect == "revision":
        observation.payload["workflow_revision_id"] = "f" * 32
    elif defect == "hash":
        observation.payload["preview_spec_hash"] = "f" * 64
    elif defect == "unvalidated":
        observation.payload["validated"] = False
    elif defect == "failed":
        observation.status = "failed"
    elif defect == "action":
        actions[-1].observation_id = "f" * 32
    elif defect == "media":
        observation.payload["preview_media_ids"] = ["media-other"]
    else:
        observation.payload["executed"] = False
    anchor = selected_workflow_projection(state, observations, actions)
    assert anchor["status"] == "unavailable" and anchor["reason"]
    assert "preview" not in anchor and "applied_graph" not in anchor


@pytest.mark.parametrize("large_field", ["texts", "warnings", "graph"])
def test_selected_anchor_size_bound_is_explicit_and_does_not_change_raw_evidence(selected: Any, large_field: str) -> None:
    store, project_id, task_id, _ = selected
    state = store.get(project_id, task_id)
    observations = store.observations(project_id, task_id)
    actions = store.actions(project_id, task_id)
    if large_field == "graph":
        actions[-1].action.graph.nodes.extend([
            MatchNode(type="match", id=f"match{index}", text="$reader.text", expected="x" * 256,
                      mode="exact", emit="all") for index in range(14)
        ])
    else:
        preview = observations[-1].payload["preview"]
        if large_field == "texts":
            preview["frames"][0]["texts"] = ["Exact raw text: " + "z" * 8000]
        else:
            preview["warnings"] = ["w" * 8000]
    before = [row.model_dump(mode="json") for row in observations]
    anchor = selected_workflow_projection(state, observations, actions)
    assert anchor["status"] == "available"
    assert len(json.dumps(anchor, ensure_ascii=False)) <= anchor["context_char_limit"] == 5000
    assert anchor["retrieve_saved_values"]["observation_id"] == observations[-1].id
    assert anchor["retrieve_saved_values"]["cursor"] is None
    if large_field != "graph":
        assert anchor["preview"]["frames"] == []
        assert anchor["preview"]["frames_page"]["omitted_for_size"] is True
    else:
        assert anchor["applied_graph"]["nodes_omitted_for_size"] is True
        assert anchor["preview"]["frames"][0]["texts"] == before[-1]["payload"]["preview"]["frames"][0]["texts"]
    assert [row.model_dump(mode="json") for row in observations] == before


def test_no_selected_workflow_keeps_existing_context_shape(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("No selected draft", "custom")
    store = InvestigationStore(service)
    task = store.create(project.id, "Investigate")
    assert "selected_workflow" not in investigation_context(store, project.id, task.id)
