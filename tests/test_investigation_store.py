"""A0 persistence invariants independent of planner quality or vision output."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from engine.investigations.store import (
    InvestigationBudgetExceeded,
    InvestigationConflict,
    InvestigationStore,
)
from engine.service import WorkspaceService
from spec.investigation import (
    ActionReceipt,
    BuilderAction,
    BuilderDecision,
    InvestigationBudget,
    NextAction,
    TaskState,
    WorkflowDecision,
)


def workspace(tmp_path: Path, budget: InvestigationBudget | None = None) -> tuple[InvestigationStore, str, str]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("A0 persistence software test", "custom")
    store = InvestigationStore(service)
    task = store.create(project.id, "Investigate the supplied images", budget)
    return store, project.id, task.id


def decision(store: InvestigationStore, project: str, task: str, action: dict[str, object] | None = None,
             references: list[str] | None = None) -> NextAction:
    return NextAction.model_validate({"type": "next_action", "state_revision": store.get(project, task).revision,
        "decision_summary": "Deterministic persistence test, not real model evidence",
        "based_on_observation_ids": references or [], "action": action or {"type": "inspect_media"}})


def capture(store: InvestigationStore, project: str, task: str, proposed: BuilderDecision,
            visible: list[str] | None = None) -> str:
    call = store.start_model_call(project, task, {"test_stub": True}, "test-model", visible)
    store.finish_model_call(project, task, call.id, proposed.model_dump(mode="json"))
    return call.id


def probe() -> dict[str, object]:
    return {"type": "run_probe", "capability_id": "model.fixture-color-v1",
        "inspected_descriptor_hash": "a" * 64, "media_id": "image-123", "source_sha256": "b" * 64,
        "transforms": [{"type": "crop", "box": [0, 0, .5, 1]}, {"type": "resize", "width": 80, "height": 60}],
        "request": {"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}}


def test_schema_discriminators_are_first_and_probe_request_compatibility() -> None:
    from engine.adapters.contracts import DetectionRequest as OldDetection
    from spec.inference_requests import DetectionRequest
    from spec.investigation import RunProbe

    assert OldDetection is DetectionRequest
    request = RunProbe.model_validate(probe())
    assert isinstance(request.request, DetectionRequest)
    assert [item.type for item in request.transforms] == ["crop", "resize"]
    schema = NextAction.model_json_schema()
    for definition in schema["$defs"].values():
        properties = definition.get("properties", {})
        if "type" in properties:
            assert next(iter(properties)) == "type"
    assert schema["properties"]["action"]["discriminator"]["propertyName"] == "type"


@pytest.mark.parametrize("change", [
    {"media_id": "../../other.png"}, {"source_sha256": "unknown"},
    {"transforms": [{"type": "crop", "box": [0, 0, 0, 1]}]},
    {"transforms": [{"type": "resize", "width": True, "height": 100}]},
    {"transforms": [{"type": "crop", "box": [0, 0, .5, float("nan")]}]},
    {"request": {"task": "shell", "command": "anything"}},
    {"request": {"task": "barcode", "model_id": "unregistered"}},
])
def test_probe_contract_rejects_untyped_commands_paths_and_bad_geometry(change: dict[str, object]) -> None:
    from spec.investigation import RunProbe
    with pytest.raises(ValidationError):
        RunProbe.model_validate(probe() | change)


def test_reservation_is_persistent_before_effect_and_completion_is_idempotent(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    reloaded = InvestigationStore(WorkspaceService(tmp_path))
    assert reloaded.get(project, task).pending_action_id == receipt.id
    assert reloaded.get(project, task).budget.actions == 1
    with pytest.raises(InvestigationConflict, match="already reserved"):
        reloaded.reserve_action(project, task, proposed)
    result = reloaded.complete_action(project, task, receipt.id, {"images": []})
    assert store.complete_action(project, task, receipt.id, {"images": []}) == result
    assert len(store.observations(project, task)) == 1
    assert store.get(project, task).latest_observation_ids == [result.id]
    with pytest.raises(InvestigationConflict, match="cannot be replaced"):
        store.complete_action(project, task, receipt.id, {"images": ["invented"]})
    with pytest.raises(InvestigationConflict, match="already reserved"):
        store.reserve_action(project, task, proposed)


def test_uncaptured_modified_and_stale_model_actions_cannot_reserve(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task)
    with pytest.raises(InvestigationConflict, match="captured"):
        store.reserve_action(project, task, proposed)
    capture(store, project, task, proposed)
    changed = proposed.model_copy(update={"decision_summary": "uncaptured change"})
    with pytest.raises(InvestigationConflict, match="differs"):
        store.reserve_action(project, task, changed)
    stale = proposed.model_copy(update={"state_revision": 5})
    with pytest.raises(InvestigationConflict, match="stale"):
        store.reserve_action(project, task, stale)
    assert store.get(project, task).budget.actions == 0


def test_schema_failure_keeps_actual_raw_response_without_authorizing_effects(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task)
    call = store.start_model_call(project, task, {}, "test-model")
    raw = {"unrecognized_output": "The actual model response"}
    saved = store.finish_model_call(project, task, call.id, raw, "Invalid next-action schema")
    assert saved.status == "failed" and saved.response == raw
    with pytest.raises(InvestigationConflict, match="completed captured"):
        store.reserve_action(project, task, proposed)


def test_observation_references_must_exist_and_have_been_exposed(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    observation = store.complete_action(project, task, receipt.id, {"values": ["actual fixture value"]})
    proposed = decision(store, project, task, references=[observation.id])
    capture(store, project, task, proposed, visible=[])
    with pytest.raises(InvestigationConflict, match="not exposed"):
        store.reserve_action(project, task, proposed)
    capture(store, project, task, proposed, visible=[observation.id])
    store.reserve_action(project, task, proposed)
    other = store.create(project, "Another investigation")
    unknown = decision(store, project, other.id, {"type": "inspect_observation", "observation_id": observation.id})
    capture(store, project, other.id, unknown)
    with pytest.raises(InvestigationConflict, match="outside"):
        store.reserve_action(project, other.id, unknown)


@pytest.mark.parametrize("limit", ["model_calls", "actions", "probes"])
def test_cumulative_budget_exhaustion_persists_terminal_status(tmp_path: Path, limit: str) -> None:
    budget = InvestigationBudget(max_model_calls=1 if limit == "model_calls" else 5,
        max_actions=1 if limit == "actions" else 5, max_probes=0 if limit == "probes" else 5)
    store, project, task = workspace(tmp_path, budget)
    proposed = decision(store, project, task, probe() if limit == "probes" else None)
    capture(store, project, task, proposed)
    if limit == "probes":
        with pytest.raises(InvestigationBudgetExceeded):
            store.reserve_action(project, task, proposed)
    else:
        receipt = store.reserve_action(project, task, proposed)
        store.complete_action(project, task, receipt.id, {})
        proposed = decision(store, project, task)
        if limit == "model_calls":
            with pytest.raises(InvestigationBudgetExceeded):
                capture(store, project, task, proposed)
        else:
            capture(store, project, task, proposed)
            with pytest.raises(InvestigationBudgetExceeded):
                store.reserve_action(project, task, proposed)
    state = store.get(project, task)
    assert state.status == "inconclusive" and "budget exhausted" in (state.stop_reason or "")
    with pytest.raises(InvestigationConflict):
        store.resume(project, task)


@pytest.mark.parametrize("pending", ["model", "action"])
def test_interrupted_pending_work_has_no_automatic_reexecution(tmp_path: Path, pending: str) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task, probe())
    call = store.start_model_call(project, task, {}, "test-model")
    action_id = None
    if pending == "action":
        store.finish_model_call(project, task, call.id, proposed.model_dump(mode="json"))
        action_id = store.reserve_action(project, task, proposed).id
    state = InvestigationStore(WorkspaceService(tmp_path)).recover_pending(project, task)
    assert state.status == "interrupted"
    assert state.pending_model_call_id is state.pending_action_id is None
    old_budget = state.budget.model_dump()
    resumed = store.resume(project, task)
    assert resumed.budget.model_dump() == old_budget
    if action_id:
        observation = store.observations(project, task)[0]
        assert observation.payload == {"effect_status": "unknown", "automatic_retry": False}
        with pytest.raises(InvestigationConflict):
            store.complete_action(project, task, action_id, {"late": True})
        assert resumed.budget.probes == 1
    else:
        with pytest.raises(InvestigationConflict, match="late"):
            store.finish_model_call(project, task, call.id, proposed.model_dump(mode="json"))


def test_ask_finish_and_workflow_transitions_derive_only_from_reserved_action(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task, {"type": "ask_user", "question": "Which object label matters?"})
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    store.complete_action(project, task, receipt.id, {"status": "completed", "question": "malicious payload question"})
    state = store.get(project, task)
    assert state.status == "awaiting_input" and state.question == "Which object label matters?"
    with pytest.raises(ValueError, match="Answer"):
        store.resume(project, task)
    store.resume(project, task, "Pallets")
    proposed = decision(store, project, task, {"type": "prepare_workflow", "summary": "Prepare the construction schema"})
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    store.complete_action(project, task, receipt.id, {})
    assert store.get(project, task).stage == "workflow"
    construction = workflow_decision(store, project, task)
    capture(store, project, task, construction)
    receipt = store.reserve_action(project, task, construction)
    store.complete_action(project, task, receipt.id, {}, "failed", "Required capability is unavailable")
    assert store.get(project, task).stage == "investigating"
    proposed = decision(store, project, task, {"type": "finish", "outcome": "blocked", "summary": "Required capability is unavailable"})
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    store.complete_action(project, task, receipt.id, {"status": "running"})
    state = store.get(project, task)
    assert state.status == "blocked" and state.stop_reason == "Required capability is unavailable"
    assert state.user_answers == ["Pallets"] and state.budget.actions == 4


def test_failed_probe_is_an_observation_not_a_prescribed_next_action(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task, probe())
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    error = {"code": "adapter_unavailable", "retryable": False}
    observation = store.complete_action(project, task, receipt.id, {"executed": False}, "failed", error)
    assert observation.error == error and observation.status == "failed"
    assert store.get(project, task).status == "running" and store.get(project, task).budget.probes == 1
    assert len(store.actions(project, task)) == 1


def test_elapsed_work_accumulates_but_waiting_for_user_does_not_reset_or_charge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.investigations.store as module
    start = datetime(2026, 10, 29, tzinfo=UTC)
    clock = [start]
    monkeypatch.setattr(module, "now", lambda: clock[0].isoformat())
    store, project, task = workspace(tmp_path, InvestigationBudget(max_elapsed_s=10))
    proposed = decision(store, project, task, {"type": "ask_user", "question": "Which label?"})
    call = store.start_model_call(project, task, {}, "test")
    clock[0] += timedelta(seconds=2)
    store.finish_model_call(project, task, call.id, proposed.model_dump(mode="json"))
    receipt = store.reserve_action(project, task, proposed)
    clock[0] += timedelta(seconds=3)
    store.complete_action(project, task, receipt.id, {})
    clock[0] += timedelta(hours=1)
    assert store.resume(project, task, "Pallet").budget.elapsed_s == 5
    call = store.start_model_call(project, task, {}, "test")
    clock[0] += timedelta(seconds=6)
    recovered = store.recover_pending(project, task)
    assert recovered.budget.elapsed_s == 11
    store.resume(project, task)
    with pytest.raises(InvestigationBudgetExceeded, match="elapsed-time"):
        store.start_model_call(project, task, {}, "test")
    assert store.get(project, task).status == "inconclusive"


def test_pause_cancels_pending_authority_and_resume_preserves_counters(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    paused = store.stop(project, task, "User paused this investigation", "paused")
    assert paused.status == "paused" and not paused.pending_action_id
    with pytest.raises(InvestigationConflict):
        store.complete_action(project, task, receipt.id, {})
    resumed = store.resume(project, task)
    assert resumed.budget == paused.budget


def test_record_ids_cannot_escape_project_root(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    for identifier in ["../outside", "/tmp/task", "not-a-record"]:
        with pytest.raises(ValueError):
            store.root(project, identifier)
    assert store.root(project, task).name == task


def workflow_decision(store: InvestigationStore, project: str, task: str,
                      evidence_ids: list[str] | None = None) -> WorkflowDecision:
    return WorkflowDecision.model_validate({"type": "workflow_decision",
        "state_revision": store.get(project, task).revision,
        "decision_summary": "Scripted store protocol test, not actual planner or inference evidence",
        "action": {"type": "construct_workflow", "media_ids": ["image-123"],
            "evidence_ids": evidence_ids or [], "graph": {"name": "Fixture workflow",
                "nodes": [{"type": "frame_sample", "id": "sample", "fps": 1},
                    {"type": "ocr", "id": "read", "image": "$sample.image",
                     "model_capability_id": "model.fixture-ocr-v1", "model_reason": "Protocol fixture"}],
                "metric": "text_accuracy", "target": 1}}})


def prepare_workflow(store: InvestigationStore, project: str, task: str) -> None:
    proposed = decision(store, project, task, {"type": "prepare_workflow", "summary": "Choose workflow schema"})
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    store.complete_action(project, task, receipt.id, {})


def preview_payload(revision: str = "a" * 32) -> dict[str, JsonValue]:
    # Typed host receipt fixture; actual compile/runtime behavior is tested by the tool service.
    return {"workflow_revision_id": revision, "spec_hash": "b" * 64, "preview_spec_hash": "b" * 64,
        "preview_media_ids": ["image-123"], "validated": True, "preview_success": True,
        "preview": {"frames": [{"image_path": "fixture.png", "texts": ["ACTUAL VALUE"]}], "elapsed_s": .1},
        "summary": "Host diagnostic extras are retained"}


def construct_preview(store: InvestigationStore, project: str, task: str,
                      revision: str = "a" * 32) -> str:
    prepare_workflow(store, project, task)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    return store.complete_action(project, task, receipt.id, preview_payload(revision)).id


def test_workflow_schema_is_separate_and_legacy_records_keep_defaults(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    assert "ConstructWorkflow" not in NextAction.model_json_schema()["$defs"]
    workflow_schema = WorkflowDecision.model_json_schema()
    assert workflow_schema["required"][0] == "type"
    assert workflow_schema["$defs"]["ConstructWorkflow"]["required"][0] == "type"
    action_schema = TypeAdapter(BuilderAction).json_schema()
    assert "construct_workflow" in action_schema["discriminator"]["mapping"]
    proposed = decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    assert isinstance(ActionReceipt.model_validate(receipt.model_dump()).decision, NextAction)
    old_task = store.get(project, task).model_dump(exclude={"selected_workflow_revision", "preview_observation_id"})
    assert TaskState.model_validate(old_task).selected_workflow_revision is None
    workflow = workflow_decision(store, project, task)
    assert isinstance(TypeAdapter(BuilderDecision).validate_python(workflow.model_dump()), WorkflowDecision)
    with pytest.raises(ValidationError):
        NextAction.model_validate(workflow.model_dump())
    for media in [[], ["a", "b", "c", "d"], ["a", "a"], ["../outside"]]:
        raw = workflow.model_dump()
        raw["action"]["media_ids"] = media
        with pytest.raises(ValidationError):
            WorkflowDecision.model_validate(raw)


def test_workflow_decisions_require_selected_stage_and_exact_captured_graph(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    with pytest.raises(InvestigationConflict, match="stage"):
        store.reserve_action(project, task, proposed)
    prepare_workflow(store, project, task)
    wrong_stage = decision(store, project, task)
    capture(store, project, task, wrong_stage)
    with pytest.raises(InvestigationConflict, match="stage"):
        store.reserve_action(project, task, wrong_stage)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    changed = proposed.model_copy(deep=True)
    changed.action.graph.name = "An uncaptured graph change"
    with pytest.raises(InvestigationConflict, match="differs"):
        store.reserve_action(project, task, changed)
    receipt = store.reserve_action(project, task, proposed)
    assert isinstance(store.actions(project, task)[-1].decision, WorkflowDecision)
    assert store.get(project, task).pending_action_id == receipt.id
    with pytest.raises(InvestigationConflict, match="already reserved"):
        store.reserve_action(project, task, proposed)


def test_construct_evidence_must_belong_to_same_investigation(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    prepare_workflow(store, project, task)
    proposed = workflow_decision(store, project, task, ["f" * 32])
    capture(store, project, task, proposed)
    with pytest.raises(InvestigationConflict, match="outside"):
        store.reserve_action(project, task, proposed)


def test_preview_selection_is_host_owned_and_finish_requires_exact_exposed_evidence(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    regular = decision(store, project, task)
    capture(store, project, task, regular)
    receipt = store.reserve_action(project, task, regular)
    store.complete_action(project, task, receipt.id, preview_payload())
    assert store.get(project, task).selected_workflow_revision is None
    preview_id = construct_preview(store, project, task)
    state = store.get(project, task)
    assert state.status == "running" and state.stage == "investigating"
    assert state.selected_workflow_revision == "a" * 32 and state.preview_observation_id == preview_id
    for revision, evidence, visible, message in [
        ("a" * 32, [preview_id], [], "not been exposed"),
        ("c" * 32, [preview_id], [preview_id], "current validated"),
        ("a" * 32, [], [preview_id], "must cite"),
    ]:
        ready = decision(store, project, task, {"type": "finish", "outcome": "draft_ready",
            "workflow_revision_id": revision, "evidence_ids": evidence, "summary": "Reviewable draft"})
        capture(store, project, task, ready, visible=visible)
        with pytest.raises(InvestigationConflict, match=message):
            store.reserve_action(project, task, ready)
    ready = decision(store, project, task, {"type": "finish", "outcome": "draft_ready",
        "workflow_revision_id": "a" * 32, "evidence_ids": [preview_id], "summary": "Reviewable draft"})
    capture(store, project, task, ready, visible=[preview_id])
    receipt = store.reserve_action(project, task, ready)
    store.complete_action(project, task, receipt.id, {"status": "approved", "workflow_revision_id": "d" * 32})
    state = store.get(project, task)
    assert state.status == "draft_ready" and state.selected_workflow_revision == "a" * 32
    with pytest.raises(InvestigationConflict, match="not running"):
        store.start_model_call(project, task, {}, "test")


@pytest.mark.parametrize("change", [
    {"workflow_revision_id": "invented"}, {"validated": False}, {"preview_success": False},
    {"spec_hash": "c" * 64}, {"preview_media_ids": ["different-image"]},
    {"preview_media_ids": ["image-123", "extra-image"]},
    {"preview": {"frames": [], "elapsed_s": .1}},
    {"preview": {"frames": [{"texts": ["Missing source path"]}], "elapsed_s": .1}},
])
def test_invalid_workflow_preview_is_durable_failure_and_allows_new_agent_action(
    tmp_path: Path, change: dict[str, JsonValue],
) -> None:
    store, project, task = workspace(tmp_path)
    prepare_workflow(store, project, task)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    payload = preview_payload() | change
    observation = store.complete_action(project, task, receipt.id, payload)
    assert observation.status == "failed"
    assert isinstance(observation.error, dict) and observation.error["code"] == "invalid_workflow_evidence"
    assert observation.payload == payload
    assert store.complete_action(project, task, receipt.id, payload) == observation
    state = store.get(project, task)
    assert state.stage == "investigating" and state.status == "running"
    assert state.selected_workflow_revision is None and state.preview_observation_id is None
    next_probe = decision(store, project, task, probe(), [observation.id])
    capture(store, project, task, next_probe)
    store.reserve_action(project, task, next_probe)


def test_failed_revision_does_not_replace_previous_success_and_later_success_does(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    first = construct_preview(store, project, task)
    prepare_workflow(store, project, task)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    store.complete_action(project, task, receipt.id, preview_payload("c" * 32), "failed", "Compiler refused graph")
    state = store.get(project, task)
    assert state.selected_workflow_revision == "a" * 32 and state.preview_observation_id == first
    second = construct_preview(store, project, task, "d" * 32)
    state = store.get(project, task)
    assert state.selected_workflow_revision == "d" * 32 and state.preview_observation_id == second
    old = decision(store, project, task, {"type": "finish", "outcome": "draft_ready",
        "workflow_revision_id": "a" * 32, "evidence_ids": [first], "summary": "Old draft"})
    capture(store, project, task, old, visible=[first, second])
    with pytest.raises(InvestigationConflict, match="current validated"):
        store.reserve_action(project, task, old)


def test_construct_interruption_returns_to_investigation_without_replaying_graph(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    prepare_workflow(store, project, task)
    proposed = workflow_decision(store, project, task)
    capture(store, project, task, proposed)
    receipt = store.reserve_action(project, task, proposed)
    recovered = store.recover_pending(project, task)
    assert recovered.status == "interrupted" and recovered.stage == "investigating"
    assert recovered.selected_workflow_revision is None
    store.resume(project, task)
    with pytest.raises(InvestigationConflict, match="cannot be replaced"):
        store.complete_action(project, task, receipt.id, preview_payload())
    assert store.actions(project, task)[-1].status == "interrupted"


def test_draft_ready_requires_preview_even_with_captured_model_claim(tmp_path: Path) -> None:
    store, project, task = workspace(tmp_path)
    ready = decision(store, project, task, {"type": "finish", "outcome": "draft_ready",
        "workflow_revision_id": "a" * 32, "summary": "The model claims it is ready"})
    capture(store, project, task, ready)
    with pytest.raises(InvestigationConflict, match="current validated"):
        store.reserve_action(project, task, ready)
    for action in [
        {"type": "finish", "outcome": "draft_ready", "summary": "No revision"},
        {"type": "finish", "outcome": "inconclusive", "workflow_revision_id": "a" * 32, "summary": "Wrong outcome"},
    ]:
        with pytest.raises(ValidationError):
            decision(store, project, task, action)
