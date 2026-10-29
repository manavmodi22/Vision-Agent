from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import time

import pytest

from agent.contracts import PatternChoice, PlanDecision, PlanResult
from agent.decisions import compile_decision
from agent.machine import Phase
from agent.state_contracts import TraceQuery
from engine.agent_state import AgentConflict, AgentStateStore
from engine.compiler import compile_pipeline
from engine.datasets import DatasetService
from engine.runtime import run_pipeline
from engine.service import WorkspaceService


def setup_project(tmp_path: Path) -> tuple[WorkspaceService, AgentStateStore, str]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Durable fixture", "pallets")
    service.demo(project.id)
    return service, AgentStateStore(service), project.id


def stage_fixture(service: WorkspaceService, store: AgentStateStore, project_id: str) -> PlanResult:
    operation = store.begin(project_id, "Count pallets", "media", "fixture-color-v1")
    decision = PlanDecision(message="Count pallets by lane.", choices=[PatternChoice(
        use_case="pallets", objects=["pallet"], count_threshold=None, metric="count_mae", target=0.5,
    )])
    model_call = store.start_call(project_id, operation.id, "llm", "test-model", {"messages": []})
    store.finish_call(project_id, operation.id, model_call.id, {"decision": decision.model_dump(mode="json")})
    store.record_decision(project_id, operation.id, decision)
    result = compile_decision(decision, "media", "fixture-color-v1")
    store.prepare_compile(project_id, operation.id, 1)
    spec = result.candidates[0]
    arguments = {"project_id": project_id, "spec": spec.model_dump(mode="json", by_alias=True)}
    call = store.start_call(project_id, operation.id, "tool", "pipeline_validate", arguments)
    compile_pipeline(spec, service.root(project_id))
    store.finish_call(project_id, operation.id, call.id, {"valid": True, "errors": []})
    call = store.start_call(project_id, operation.id, "tool", "pipeline_run", arguments)
    preview = run_pipeline(spec, service.root(project_id), max_frames=5)
    store.finish_call(project_id, operation.id, call.id, preview.model_dump(mode="json"))
    result.operation_id, result.tool_calls, result.elapsed_s = operation.id, 2, 0.5
    store.stage(project_id, operation.id, result)
    return result


def test_atomic_conflicting_starts_do_not_overwrite(tmp_path: Path) -> None:
    _, _, project_id = setup_project(tmp_path)

    def start() -> str:
        store = AgentStateStore(WorkspaceService(tmp_path))
        try:
            return store.begin(project_id, "Count", "media", "fixture-color-v1").id
        except AgentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: start(), range(2)))
    assert outcomes.count("conflict") == 1
    assert len(AgentStateStore(WorkspaceService(tmp_path)).runs(project_id)) == 1


def test_commit_requires_exact_result_and_operation_token(tmp_path: Path) -> None:
    service, store, project_id = setup_project(tmp_path)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    changed = result.model_copy(deep=True)
    changed.candidates[0].eval.target = 50
    with pytest.raises(AgentConflict, match="exact staged result"):
        store.commit_plan(project_id, result.operation_id, changed, "changed")
    with pytest.raises(AgentConflict, match="token"):
        store.commit_plan(project_id, "0" * 32, result, "wrong token")
    project = store.commit_plan(project_id, result.operation_id, result, "Count pallets")
    assert len(project.candidates) == 1
    assert store.get(project_id).state.phase is Phase.EVALUATE
    with pytest.raises(AgentConflict):
        store.commit_plan(project_id, result.operation_id, result, "duplicate")


def test_ontology_change_invalidates_pending_operation(tmp_path: Path) -> None:
    service, store, project_id = setup_project(tmp_path)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    datasets = DatasetService(service)
    manifest = datasets.manifest(project_id)
    classes = [item.model_copy(update={"color": "#FFFFFF"}) for item in manifest.classes]
    datasets.save_classes(project_id, manifest.revision, classes)
    with pytest.raises(AgentConflict):
        store.commit_plan(project_id, result.operation_id, result, "stale")
    assert store.operation(project_id, result.operation_id).status == "invalidated"
    assert not service.get_project(project_id).candidates


def test_dead_owner_reconciles_pending_call_and_preserves_budget(tmp_path: Path) -> None:
    service, store, project_id = setup_project(tmp_path)
    operation = store.begin(project_id, "Original brief", "media", "fixture-color-v1")
    store.start_call(project_id, operation.id, "llm", "offline-model", {"prompt": "Original brief"})
    operation = store.operation(project_id, operation.id)
    operation.owner_pid = 99999999
    store._save_operation(operation)
    restored = AgentStateStore(WorkspaceService(tmp_path))
    state = restored.get(project_id)
    old = restored.operation(project_id, operation.id)
    assert state.active_operation_id is None
    assert state.brief == "Original brief"
    assert old.status == "interrupted" and old.calls[0].status == "interrupted"
    assert old.state.budget.model_calls == 1
    assert not state.state.deployment_approved
    new = restored.begin(project_id, "Try again", "media", "fixture-color-v1")
    assert new.id != operation.id and new.state.budget.model_calls == 0
    assert restored.operation(project_id, operation.id).state.budget.model_calls == 1


def test_pending_commit_expires_without_approval(tmp_path: Path) -> None:
    service, store, project_id = setup_project(tmp_path)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    operation = store.operation(project_id, result.operation_id)
    operation.deadline = time() - 1
    store._save_operation(operation)
    state = store.get(project_id)
    assert state.active_operation_id is None and not state.state.deployment_approved
    assert not service.get_project(project_id).candidates


def test_phase_comes_from_actual_evaluation_and_deployment_files(tmp_path: Path) -> None:
    service, store, project_id = setup_project(tmp_path)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    store.commit_plan(project_id, result.operation_id, result, "Count pallets")
    service.evaluate(project_id)
    assert store.reconcile(project_id, "evaluate").state.phase is Phase.DEPLOY
    assert not store.get(project_id).state.deployment_approved
    service.deploy(project_id, 0, True)
    assert store.reconcile(project_id, "deploy").state.phase is Phase.OPERATE
    assert store.get(project_id).state.deployment_approved
    labels = service.annotations(project_id)
    labels.annotations[0].reviewed = False
    service.save_annotations(project_id, labels)
    assert not store.reconcile(project_id, "labels_changed").state.deployment_approved


def test_local_otel_spans_and_replay_have_no_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, store, project_id = setup_project(tmp_path)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    store.commit_plan(project_id, result.operation_id, result, "Count pallets")
    spans = store.traces.query(project_id, TraceQuery(operation_id=result.operation_id))
    assert len(spans) == 4  # One actual test model attempt, two tools, one run summary.
    assert {span.kind for span in spans} == {"llm", "tool", "run"}
    assert len({span.trace_id for span in spans}) == 1
    before = service.get_project(project_id).model_dump_json()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Replay executed an effect")

    monkeypatch.setattr("engine.runtime.run_pipeline", forbidden)
    monkeypatch.setattr(service, "save_candidates", forbidden)
    replay = store.replay(project_id, result.operation_id)
    assert replay.reproduced and replay.dry_run and not replay.effects_executed
    assert replay.captured_tool_calls == 2 and replay.captured_model_calls == 1
    assert service.get_project(project_id).model_dump_json() == before


@pytest.mark.parametrize("prompt,expected_users", [("Count pallets", 1), ("Count pallets by a revised rule", 2)])
def test_resume_commit_deduplicates_only_the_same_last_user_goal(tmp_path: Path, prompt: str, expected_users: int) -> None:
    from engine.store.models import Message
    service, store, project_id = setup_project(tmp_path)
    project = service.get_project(project_id)
    project.messages = [Message(role="user", content="Count pallets"),
                        Message(role="assistant", content="Draw the requested region before I continue")]
    service.repository.save(project)
    result = stage_fixture(service, store, project_id)
    assert result.operation_id
    updated = store.commit_plan(project_id, result.operation_id, result, prompt)
    assert len([message for message in updated.messages if message.role == "user"]) == expected_users
    assert updated.messages[1].content == "Draw the requested region before I continue"
    assert updated.messages[-1].role == "assistant" and updated.clarification_count == 0
