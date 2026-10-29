import time

import pytest

from agent.machine import AgentBudget, AgentError, AgentState, EvaluationEvidence, Phase


def evaluated_state(passed: bool = True) -> AgentState:
    state = AgentState()
    state.confirm_brief(confirmed=True)
    state.finish_plan(1)
    state.finish_compile(1)
    state.record_evaluation(EvaluationEvidence(
        spec_hash="pipeline-v1", dataset_hash="labels-v1", passed=passed,
        sample_count=10, reviewed=True,
    ))
    return state


def test_cannot_skip_directly_to_deployment() -> None:
    state = AgentState()
    with pytest.raises(AgentError, match="current phase"):
        state.approve_deployment(spec_hash="x", dataset_hash="x", human_approved=True)
    with pytest.raises(AgentError, match="Expected phase"):
        state.finish_compile(1)
    with pytest.raises(AgentError, match="human"):
        state.confirm_brief(confirmed=False)


def test_passing_metrics_still_require_a_human_click() -> None:
    state = evaluated_state()
    assert state.phase is Phase.DEPLOY
    with pytest.raises(AgentError, match="human deployment click"):
        state.approve_deployment(spec_hash="pipeline-v1", dataset_hash="labels-v1", human_approved=False)
    state.approve_deployment(spec_hash="pipeline-v1", dataset_hash="labels-v1", human_approved=True)
    assert state.phase is Phase.OPERATE
    assert state.deployment_approved


def test_failed_metrics_need_recorded_override_and_stale_hash_cannot_override() -> None:
    state = evaluated_state(False)
    with pytest.raises(AgentError, match="override reason"):
        state.approve_deployment(spec_hash="pipeline-v1", dataset_hash="labels-v1", human_approved=True)
    with pytest.raises(AgentError, match="stale"):
        state.approve_deployment(spec_hash="pipeline-v2", dataset_hash="labels-v1", human_approved=True,
                                 override_reason="Accepting for supervised trial")
    state.approve_deployment(spec_hash="pipeline-v1", dataset_hash="labels-v1", human_approved=True,
                             override_reason="Accepting for supervised trial")
    assert state.override_reason == "Accepting for supervised trial"


def test_unreviewed_labels_never_create_evidence() -> None:
    state = AgentState(phase=Phase.EVALUATE)
    with pytest.raises(AgentError, match="human-reviewed"):
        state.record_evaluation(EvaluationEvidence(
            spec_hash="x", dataset_hash="y", passed=True, sample_count=10, reviewed=False,
        ))
    assert state.evaluation is None


def test_invalidation_clears_approval_and_evidence() -> None:
    state = evaluated_state()
    state.approve_deployment(spec_hash="pipeline-v1", dataset_hash="labels-v1", human_approved=True)
    state.invalidate_evidence()
    assert state.phase is Phase.COMPILE
    assert state.evaluation is None
    assert not state.deployment_approved


def test_tools_are_checked_against_phase_before_dispatch() -> None:
    state = AgentState()
    with pytest.raises(AgentError, match="not allowed"):
        state.authorize_tool("pipeline_run")
    state.authorize_tool("frames_sample")
    state.confirm_brief(confirmed=True)
    state.authorize_tool("blocks_list")
    with pytest.raises(AgentError, match="not allowed"):
        state.authorize_tool("media_import")
    with pytest.raises(AgentError, match="not allowed"):
        state.authorize_tool("pipeline_deploy")
    assert state.budget.tool_calls == 2


def test_budget_survives_state_roundtrip() -> None:
    state = AgentState(budget=AgentBudget(max_tool_calls=1))
    state.authorize_tool("frames_sample")
    restored = AgentState.model_validate_json(state.model_dump_json())
    with pytest.raises(AgentError, match="tool-call budget"):
        restored.authorize_tool("frames_sample")


def test_wall_and_training_limits() -> None:
    state = AgentState(budget=AgentBudget(started_at=time.time() - 20, max_wall_seconds=10))
    with pytest.raises(AgentError, match="wall-clock"):
        state.authorize_tool("frames_sample")
    state = evaluated_state(False)
    with pytest.raises(AgentError, match="training-minute"):
        state.specialize(31)
    state.specialize(20)
    assert state.phase is Phase.SPECIALIZE
    state.authorize_tool("train_status")


def test_every_candidate_must_compile() -> None:
    state = AgentState()
    state.confirm_brief(confirmed=True)
    state.finish_plan(2)
    with pytest.raises(AgentError, match="Every candidate"):
        state.finish_compile(1)
    state.finish_compile(2)
    assert state.phase is Phase.EVALUATE
