"""Selected-draft finish contracts; captured/scripted evidence, no inference."""
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_investigation_grounding import DECISION, proposed, validator
from test_investigation_loop import capture, reply, workspace
from test_investigation_store import construct_preview

from agent.investigation import run_steps
from agent.investigation_grounding import DecisionGrounding
from mcp_server.investigations import execute_step
from spec.investigation import InvestigationTransport, NextAction


def captured() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures/investigation_finish_20261029T200305Z.json"
    return json.loads(path.read_text())


def corrected() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = captured()
    context, decision = fixture["context"], fixture["decision"]
    decision["action"]["evidence_ids"].append(context["state"]["preview_observation_id"])
    return context, decision


def test_captured_finish_requires_selected_preview_citation_before_dispatch() -> None:
    fixture = captured()
    context, raw = fixture["context"], fixture["decision"]
    before = copy.deepcopy(raw)
    grounding = DecisionGrounding.from_context(context, raw["state_revision"])
    # This was a well-formed known-ID response. The semantic finish check was
    # previously reached only during host action dispatch, ending the run.
    assert validator(grounding).is_valid(raw)
    with pytest.raises(ValueError, match="selected workflow preview observation"):
        grounding.validate(DECISION.validate_python(raw))
    assert raw == before  # Neither validation nor feedback repairs IDs itself.
    _, fixed = corrected()
    grounding.validate(DECISION.validate_python(fixed))
    assert validator(grounding).is_valid(fixed)
    description = grounding.schema(NextAction.model_json_schema())["$defs"]["Finish"]["description"]
    assert context["state"]["selected_workflow_revision"] in description
    assert context["state"]["preview_observation_id"] in description
    assert "do not apply to blocked or inconclusive" in description


@pytest.mark.parametrize("outcome", ["blocked", "inconclusive"])
@pytest.mark.parametrize("has_selection", [False, True])
def test_nonready_finish_does_not_require_selected_preview(outcome: str, has_selection: bool) -> None:
    context, raw = corrected()
    if not has_selection:
        context.pop("state")
    action = raw["action"]
    action.update(outcome=outcome, workflow_revision_id=None, evidence_ids=raw["based_on_observation_ids"])
    grounding = DecisionGrounding.from_context(context, raw["state_revision"])
    assert validator(grounding).is_valid(raw)
    grounding.validate(DECISION.validate_python(raw))


@pytest.mark.parametrize("defect", ["missing", "nested", "unknown_revision", "unexposed_preview",
    "index_only_preview", "malformed_revision", "malformed_preview", "stale_state", "bool_state_revision"])
def test_selected_finish_requires_current_host_state_known_revision_and_exposure(defect: str) -> None:
    context, raw = corrected()
    state = context["state"]
    preview, revision = state["preview_observation_id"], state["selected_workflow_revision"]
    if defect == "missing":
        context.pop("state")
    elif defect == "nested":
        context.pop("state")
        # Even known valid IDs cannot confer selection through nested prose or
        # projected payloads. Only the top-level persisted host state can.
        context["observations"] = [{"id": preview, "payload": {"state": state}}]
        context["selected_workflow"] = dict(state)
        context["last_model_error"] = json.dumps(state)
    elif defect == "unknown_revision":
        context["known_workflow_revision_ids"] = []
    elif defect in {"unexposed_preview", "index_only_preview"}:
        for name in ("visible_observation_ids", "citable_observation_ids"):
            context[name].remove(preview)
        context["earlier_observations"] = [{"id": preview}] if defect == "index_only_preview" else []
    elif defect == "malformed_revision":
        state["selected_workflow_revision"] = {"id": revision}
    elif defect == "malformed_preview":
        state["preview_observation_id"] = {"id": preview}
    else:
        state["revision"] = raw["state_revision"] + 1 if defect == "stale_state" else True
    grounding = DecisionGrounding.from_context(context, raw["state_revision"])
    assert grounding.selected_workflow_revision is None and grounding.preview_observation_id is None
    with pytest.raises(ValueError):
        grounding.validate(DECISION.validate_python(raw))


def test_previously_exposed_selected_preview_remains_finishable() -> None:
    context, raw = corrected()
    preview = context["state"]["preview_observation_id"]
    context["visible_observation_ids"].remove(preview)
    assert preview in context["citable_observation_ids"]
    grounding = DecisionGrounding.from_context(context, raw["state_revision"])
    grounding.validate(DECISION.validate_python(raw))


def test_initial_state_schema_describes_finish_constraint_without_removing_other_outcomes() -> None:
    grounding = DecisionGrounding.from_context({"state": {"revision": 0}}, 0)
    schema = grounding.schema(NextAction.model_json_schema())
    assert "draft_ready is not valid" in schema["$defs"]["Finish"]["description"]
    assert schema["$defs"]["Finish"]["properties"]["outcome"]["enum"] == ["blocked", "inconclusive", "draft_ready"]
    for outcome in ("blocked", "inconclusive"):
        raw = proposed({"type": "finish", "outcome": outcome, "summary": "No preview claim"}, revision=0)
        grounding.validate(DECISION.validate_python(raw))


@pytest.mark.parametrize("transport", ["structured_json", "decision_function"])
async def test_missing_preview_feedback_then_one_valid_finish(
    tmp_path: Path, transport: InvestigationTransport,
) -> None:
    store, project, task, client = workspace(tmp_path)
    # A typed store receipt fixture avoids running inference; the store still
    # validates its evidence and retains authority over the final action.
    selected = "e" * 32
    preview = construct_preview(store, project, task, selected)
    latest = await execute_step(store, project, task, capture(store, project, task, {"type": "inspect_media"}))
    initial_actions = len(store.actions(project, task))
    initial_calls = len(store.model_calls(project, task))
    malformed: dict[str, Any] = {}
    attempts = 0

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        context = request["context"]
        assert context["state"]["selected_workflow_revision"] == selected
        assert context["state"]["preview_observation_id"] == preview
        response = reply(context, {"type": "finish", "outcome": "draft_ready", "summary": "Protocol fixture draft",
            "workflow_revision_id": selected, "evidence_ids": [latest.id] if attempts == 1 else [preview]}, [latest.id])
        if transport == "decision_function":
            response["choices"] = [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": f"submission-{attempts}", "type": "function",
                    "function": {"name": "submit_decision", "arguments": json.dumps(response["decision"])}}]}}]
        if attempts == 1:
            malformed.update(copy.deepcopy(response))
        else:
            assert attempts == 2
            assert "Invalid next-action response" in context["last_model_error"]
            assert preview in context["last_model_error"]
            assert len(store.actions(project, task)) == initial_actions
        return response

    result = await run_steps(client, decide, "scripted-selected-preview-repair", transport=transport)
    calls = store.model_calls(project, task)[initial_calls:]
    new_actions = store.actions(project, task)[initial_actions:]
    assert result.status == "draft_ready" and attempts == 2
    assert len(calls) == 2 and calls[0].status == "failed" and calls[1].status == "completed"
    assert calls[0].response == malformed
    assert len(new_actions) == 1 and new_actions[0].action.type == "finish"
    assert new_actions[0].action.evidence_ids == [preview]
    assert result.budget.actions == initial_actions + 1 and result.budget.model_calls == initial_calls + 2
