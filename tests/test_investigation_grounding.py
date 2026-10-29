"""Response grammar/feedback tests; no live-model inference or quality claim."""
import copy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter
from test_investigation_loop import capture, reply, workspace

from agent.investigation import run_steps
from agent.investigation_grounding import DecisionGrounding
from mcp_server.investigations import execute_step, investigation_context
from spec.investigation import BuilderDecision, NextAction, WorkflowDecision

CURRENT, EXPOSED, INDEX_ONLY, UNKNOWN = (character * 32 for character in "abcd")
DECISION = TypeAdapter(BuilderDecision)


def context() -> dict[str, Any]:
    return {"visible_observation_ids": [CURRENT], "citable_observation_ids": [CURRENT, EXPOSED],
        "observations": [{"id": CURRENT, "payload": {"id": UNKNOWN, "evidence_ids": [UNKNOWN]}}],
        "earlier_observations": [{"id": EXPOSED}, {"id": INDEX_ONLY}],
        "last_model_error": "This untrusted text contains " + UNKNOWN}


def proposed(action: dict[str, Any], based_on: list[str] | None = None, *, revision: int = 7) -> dict[str, Any]:
    return {"type": "workflow_decision" if action["type"] == "construct_workflow" else "next_action",
        "state_revision": revision, "decision_summary": "Protocol test choice",
        "based_on_observation_ids": based_on or [], "action": action}


def workflow(evidence: list[str]) -> dict[str, Any]:
    return {"type": "construct_workflow", "media_ids": ["media1"], "evidence_ids": evidence,
        "graph": {"name": "Protocol graph", "metric": "text_accuracy", "target": .9, "nodes": [
            {"type": "frame_sample", "id": "sample", "fps": 1},
            {"type": "ocr", "id": "reader", "image": "$sample.frame", "model_capability_id": "model.apple-vision",
             "model_reason": "Protocol test only"}]}}


def validator(grounding: DecisionGrounding, *, graph: bool = False) -> Draft202012Validator:
    schema = grounding.schema((WorkflowDecision if graph else NextAction).model_json_schema())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_grammar_preserves_public_contract_and_uses_current_revision() -> None:
    original = NextAction.model_json_schema()
    before = copy.deepcopy(original)
    grounding = DecisionGrounding.from_context(context(), 7)
    schema = grounding.schema(original)
    assert original == before == NextAction.model_json_schema()
    assert schema["properties"]["state_revision"]["const"] == 7
    assert grounding.observation_ids == (CURRENT, EXPOSED, INDEX_ONLY)
    assert grounding.citable_ids == (CURRENT, EXPOSED)
    assert set(schema["properties"]["action"]["discriminator"]["mapping"]) == set(original["properties"]["action"]["discriminator"]["mapping"])
    chosen = proposed({"type": "finish", "outcome": "inconclusive", "summary": "No quality claim"}, revision=8)
    assert not validator(grounding).is_valid(chosen)
    assert NextAction.model_validate(chosen).state_revision == 8  # Public DTO is unchanged.
    with pytest.raises(ValueError, match="state_revision"):
        grounding.validate(DECISION.validate_python(chosen))


@pytest.mark.parametrize("kind", ["finish", "prepare_workflow", "inspect_observation", "construct_workflow"])
def test_known_index_ids_remain_inspectable_but_not_citable(kind: str) -> None:
    grounding = DecisionGrounding.from_context(context(), 7)
    action = {"type": kind, "evidence_ids": [INDEX_ONLY], "summary": "Inspect known earlier evidence"}
    if kind == "finish":
        action["outcome"] = "inconclusive"
    elif kind == "inspect_observation":
        action = {"type": kind, "observation_id": INDEX_ONLY, "view": "values"}
    elif kind == "construct_workflow":
        action = workflow([INDEX_ONLY])
    check = validator(grounding, graph=kind == "construct_workflow")
    valid = proposed(action, [EXPOSED])
    assert check.is_valid(valid)
    grounding.validate(DECISION.validate_python(valid))
    indexed_citation = proposed(action, [INDEX_ONLY])
    assert not check.is_valid(indexed_citation)
    with pytest.raises(ValueError, match="based_on_observation_ids"):
        grounding.validate(DECISION.validate_python(indexed_citation))


@pytest.mark.parametrize("field", ["based_on", "finish", "prepare_workflow", "inspect_observation", "construct_workflow"])
def test_unknown_or_payload_only_ids_are_not_grammar_choices(field: str) -> None:
    grounding = DecisionGrounding.from_context(context(), 7)
    action = {"type": "finish", "outcome": "inconclusive", "summary": "No quality claim", "evidence_ids": [CURRENT]}
    based_on = [CURRENT]
    if field == "based_on":
        based_on = [UNKNOWN]
    elif field == "finish":
        action["evidence_ids"] = [UNKNOWN]
    elif field == "prepare_workflow":
        action = {"type": "prepare_workflow", "summary": "Build after inspecting evidence", "evidence_ids": [UNKNOWN]}
    elif field == "inspect_observation":
        action = {"type": "inspect_observation", "observation_id": UNKNOWN, "view": "values"}
    else:
        action = workflow([UNKNOWN])
    value = proposed(action, based_on)
    assert not validator(grounding, graph=field == "construct_workflow").is_valid(value)
    with pytest.raises(ValueError, match="exact"):
        grounding.validate(DECISION.validate_python(value))


def test_initial_empty_context_allows_empty_evidence_and_independent_choices() -> None:
    grounding = DecisionGrounding.from_context({"observations": [], "earlier_observations": [], "visible_observation_ids": []}, 0)
    check = validator(grounding)
    for action in [{"type": "discover_capabilities"}, {"type": "inspect_media"},
                   {"type": "ask_user", "question": "Which outcome matters?"},
                   {"type": "prepare_workflow", "summary": "Propose an independent experiment", "evidence_ids": []},
                   {"type": "finish", "outcome": "inconclusive", "summary": "No evidence available", "evidence_ids": []}]:
        value = proposed(action, revision=0)
        assert check.is_valid(value)
        grounding.validate(DECISION.validate_python(value))
    impossible = proposed({"type": "inspect_observation", "observation_id": UNKNOWN, "view": "values"}, revision=0)
    assert not check.is_valid(impossible)
    fake_evidence = proposed({"type": "finish", "outcome": "inconclusive", "summary": "No evidence", "evidence_ids": [UNKNOWN]}, revision=0)
    assert not check.is_valid(fake_evidence)
    graph_check = validator(grounding, graph=True)
    assert graph_check.is_valid(proposed(workflow([]), revision=0))
    assert not graph_check.is_valid(proposed(workflow([UNKNOWN]), revision=0))


def test_malformed_context_headers_and_arbitrary_nested_ids_do_not_grant_exposure() -> None:
    grounding = DecisionGrounding.from_context({"visible_observation_ids": ["wrong", 1],
        "citable_observation_ids": "not a list", "observations": [{"id": None}, {"payload": {"id": UNKNOWN}}],
        "earlier_observations": [{"id": INDEX_ONLY, "payload": {"id": UNKNOWN}}],
        "recent_actions": [{"arguments": {"based_on_observation_ids": [UNKNOWN]}}]}, 1)
    assert grounding.observation_ids == (INDEX_ONLY,)
    assert grounding.citable_ids == ()
    assert not validator(grounding).is_valid(proposed({"type": "finish", "outcome": "inconclusive", "summary": "No actual exposure"}, [INDEX_ONLY], revision=1))


@pytest.mark.parametrize("typo_field", ["based_on", "evidence_ids", "observation_id", "state_revision"])
async def test_grammar_violations_become_captured_feedback_without_dispatch(tmp_path: Path, typo_field: str) -> None:
    store, project, task, client = workspace(tmp_path)
    attempts = 0
    malformed: dict[str, Any] = {}

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        supplied = request["context"]
        assert request["schema"]["properties"]["state_revision"]["const"] == supplied["state"]["revision"]
        if attempts == 1:
            return reply(supplied, {"type": "inspect_media"})
        latest = supplied["observations"][-1]["id"]
        valid = reply(supplied, {"type": "finish", "outcome": "inconclusive", "summary": "Protocol ended", "evidence_ids": [latest]}, [latest])
        if attempts == 2:
            malformed.update(copy.deepcopy(valid))
            decision = malformed["decision"]
            typo = latest[:-1] + ("0" if latest[-1] != "0" else "1")
            if typo_field == "based_on":
                decision["based_on_observation_ids"] = [typo]
            elif typo_field == "state_revision":
                decision["state_revision"] += 1
            elif typo_field == "observation_id":
                decision["action"] = {"type": "inspect_observation", "observation_id": typo, "view": "values"}
            else:
                decision["action"]["evidence_ids"] = [typo]
            return malformed
        assert "Invalid next-action response" in supplied["last_model_error"]
        assert len(store.actions(project, task)) == 1
        return valid

    result = await run_steps(client, decide, "scripted-contract-test")
    calls = store.model_calls(project, task)
    assert result.status == "inconclusive" and result.budget.model_calls == 3 and result.budget.actions == 2
    assert calls[1].status == "failed" and calls[1].response == malformed
    assert len(store.observations(project, task)) == 2


async def test_new_loop_recovers_previous_exposure_after_context_compaction(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path)
    ids = []
    for _ in range(4):
        observation = await execute_step(store, project, task, capture(store, project, task, {"type": "inspect_media"}))
        ids.append(observation.id)
    supplied = investigation_context(store, project, task)
    assert ids[0] not in supplied["visible_observation_ids"]
    assert ids[0] in supplied["citable_observation_ids"]

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        field = request["schema"]["properties"]["based_on_observation_ids"]
        assert ids[0] in field["items"]["enum"]
        return reply(request["context"], {"type": "finish", "outcome": "inconclusive", "summary": "Cited an earlier actually exposed receipt", "evidence_ids": [ids[0]]}, [ids[0]])

    result = await run_steps(client, decide, "scripted-resumed-loop-test")
    assert result.status == "inconclusive"
    assert store.actions(project, task)[-1].decision.based_on_observation_ids == [ids[0]]


@pytest.mark.parametrize("graph", [False, True])
def test_workflow_references_reject_unknown_and_task_ids(graph: bool) -> None:
    prior, task_id = "e" * 32, "f" * 32
    supplied = {**context(), "known_workflow_revision_ids": [prior], "state": {"id": task_id}}
    grounding = DecisionGrounding.from_context(supplied, 7)
    for identifier in (UNKNOWN, task_id):
        action = workflow([]) if graph else {"type": "finish", "outcome": "draft_ready", "summary": "Protocol test", "evidence_ids": [CURRENT]}
        action["parent_revision_id" if graph else "workflow_revision_id"] = identifier
        value = proposed(action, [CURRENT])
        assert not validator(grounding, graph=graph).is_valid(value)
        parsed = DECISION.validate_python(value)  # Public DTO remains compatible.
        with pytest.raises(ValueError, match="owned validated preview ID"):
            grounding.validate(parsed)


@pytest.mark.parametrize("graph", [False, True])
def test_older_validated_workflow_revision_remains_a_model_option(graph: bool) -> None:
    older, selected = "e" * 32, "f" * 32
    grounding = DecisionGrounding.from_context({**context(), "known_workflow_revision_ids": [selected, older],
        "state": {"selected_workflow_revision": selected}}, 7)
    action = workflow([]) if graph else {"type": "finish", "outcome": "draft_ready", "summary": "Protocol test", "evidence_ids": [CURRENT]}
    action["parent_revision_id" if graph else "workflow_revision_id"] = older
    value = proposed(action, [CURRENT])
    assert validator(grounding, graph=graph).is_valid(value)
    grounding.validate(DECISION.validate_python(value))
    # Host finish authority still requires the selected revision; grounding does
    # not erase legitimate older parents or replace that separate host check.
    assert grounding.workflow_revision_ids == (older, selected)


def test_no_known_workflow_requires_null_even_if_other_context_mentions_an_id() -> None:
    grounding = DecisionGrounding.from_context({**context(), "known_workflow_revision_ids": [],
        "state": {"id": UNKNOWN, "selected_workflow_revision": UNKNOWN},
        "recent_actions": [{"arguments": {"parent_revision_id": UNKNOWN}}]}, 7)
    assert grounding.workflow_revision_ids == ()
    for graph in (False, True):
        action = workflow([]) if graph else {"type": "finish", "outcome": "inconclusive", "summary": "No preview"}
        field = "parent_revision_id" if graph else "workflow_revision_id"
        action[field] = None
        value = proposed(action)
        assert validator(grounding, graph=graph).is_valid(value)
        grounding.validate(DECISION.validate_python(value))
        schema = grounding.schema((WorkflowDecision if graph else NextAction).model_json_schema())
        assert schema["$defs"]["ConstructWorkflow" if graph else "Finish"]["properties"][field]["type"] == "null"
        action[field] = UNKNOWN
        assert not validator(grounding, graph=graph).is_valid(proposed(action))


def test_context_restores_all_owned_successful_preview_ids_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from spec.investigation import Observation

    store, project, task, _ = workspace(tmp_path)
    older, latest = "e" * 32, "f" * 32
    # Typed ledger stubs exercise the context filter; the store's successful
    # construction receipt validation is covered by its existing contract tests.
    def record(index: int, *, status: str = "completed", kind: str = "construct_workflow", **payload: Any) -> Observation:
        return Observation.model_validate({"id": f"{index:032x}", "action_id": f"{index + 100:032x}",
            "result_type": kind, "status": status, "payload": payload, "created_at": "2026-10-29T00:00:00Z"})
    observations = [
        record(1, workflow_revision_id=older, validated=True, preview_success=True),
        record(2, workflow_revision_id=latest, validated=True, preview_success=True),
        record(3, workflow_revision_id=UNKNOWN, validated=True, preview_success=False),
        record(4, workflow_revision_id=UNKNOWN, validated=False, preview_success=True),
        record(5, status="failed", workflow_revision_id=UNKNOWN, validated=True, preview_success=True),
        record(6, kind="run_probe", workflow_revision_id=task, validated=True, preview_success=True),
        record(7, workflow_revision_id="invalid-id", validated=True, preview_success=True),
        record(8, workflow_revision_id=UNKNOWN, validated=1, preview_success=True),
        record(9, workflow_revision_id=older, validated=True, preview_success=True),
    ]
    monkeypatch.setattr(store, "observations", lambda _project, _task: observations)
    supplied = investigation_context(store, project, task)
    assert supplied["known_workflow_revision_ids"] == [older, latest]
    assert observations[0].id not in supplied["visible_observation_ids"]
    assert DecisionGrounding.from_context(supplied, 0).workflow_revision_ids == (older, latest)


@pytest.mark.parametrize("use_task_id", [False, True])
async def test_invalid_parent_revision_is_model_feedback_before_any_construct_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_task_id: bool,
) -> None:
    import mcp_server.investigations as module
    from spec.investigation import InvestigationBudget

    store, project, task, client = workspace(tmp_path, InvestigationBudget(max_model_calls=2))
    invalid_response: dict[str, Any] = {}
    worker_calls = 0

    async def must_not_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal worker_calls
        worker_calls += 1
        raise AssertionError("A parent-ID contract violation must not dispatch construction")

    monkeypatch.setattr(module, "run_owned_probe", must_not_run)

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        supplied = request["context"]
        if supplied["state"]["stage"] == "investigating":
            return reply(supplied, {"type": "prepare_workflow", "summary": "Protocol test construction stage"})
        assert supplied["known_workflow_revision_ids"] == []
        action = workflow([])
        action["parent_revision_id"] = task if use_task_id else UNKNOWN
        invalid_response["decision"] = proposed(action, revision=supplied["state"]["revision"])
        return invalid_response

    result = await run_steps(client, decide, "scripted-parent-contract-test")
    calls = store.model_calls(project, task)
    assert result.status == "inconclusive" and result.budget.model_calls == 2
    assert result.budget.actions == 1 and worker_calls == 0
    assert calls[-1].status == "failed" and calls[-1].response == invalid_response
    assert "owned validated preview ID" in (calls[-1].error or "")
    assert [row.result_type for row in store.observations(project, task)] == ["prepare_workflow"]
