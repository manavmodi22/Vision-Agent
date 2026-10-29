"""Actual durable/MCP fixture evidence, separate from live model comprehension."""
import json
from pathlib import Path
from time import time

import pytest

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from agent.executor import execute_candidates
from agent.machine import AgentConflict, AgentState, Phase
from agent.mcp_client import connect_tools
from agent.skills import select_skills
from engine.agent_state import AgentStateStore
from engine.builds.manager import BuildManager
from engine.builds.store import BuildStore
from engine.platform.store import PlatformStore
from engine.service import WorkspaceService
from spec.models import PipelineSpec


def fixture(root: Path) -> tuple[WorkspaceService, str, PipelineSpec, PlanDecision]:
    service = WorkspaceService(root)
    project = service.create_project("Plan evidence fixture", "custom")
    service.demo(project.id)
    choice = PlanDecision(message="Count pallets", choices=[PatternChoice(use_case="custom", objects=["pallet"],
        count_threshold=None, metric="count_mae", target=.5)])
    candidate = compile_decision(choice, "media", "fixture-color-v1").candidates[0]
    return service, project.id, candidate, choice


def test_plan_is_saved_before_compilation_and_cannot_be_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, project_id, candidate, decision = fixture(tmp_path)
    state = AgentStateStore(service)
    operation = state.begin(project_id, "Count pallets", "media", "fixture-color-v1")
    state.record_decision(project_id, operation.id, decision)
    def no_compile(*args: object, **kwargs: object) -> None:
        pytest.fail("Publishing a plan must not compile or preview")
    monkeypatch.setattr("engine.compiler.compile_pipeline", no_compile)
    state.prepare_compile(project_id, operation.id, 1)
    plan = state.platform.plans(project_id)[0]
    assert plan.candidates == [candidate] and plan.goal == "Count pallets"
    assert all([plan.assumptions, plan.required_capabilities, plan.experiments, plan.metrics,
                plan.stop_conditions, plan.human_checkpoints, plan.snapshot.dataset_hash])
    assert not state.platform.events(project_id)
    changed = plan.model_copy(update={"goal": "Changed without a revision"})
    with pytest.raises(AgentConflict, match="immutable"):
        state.platform.immutable(state.platform.path(project_id, "plans", plan.id), changed)
    assert state.platform.plan(project_id, plan.id) == plan


@pytest.mark.parametrize("change", ["threshold", "labels", "pixels", "settings", "goal", "model", "regions"])
def test_changed_snapshot_rejects_execution_before_action(tmp_path: Path, change: str) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    service.save_candidates(project_id, [candidate], "Count pallets")
    platform = PlatformStore(service)
    plan, execution = platform.publish(project_id, "1" * 32, "Count pallets", [candidate], Phase.COMPILE, "test")
    if change in {"threshold", "goal", "model"}:
        project = service.get_project(project_id)
        if change == "threshold":
            project.candidates[0].eval.target = 100
        elif change == "goal":
            project.brief = "A different task"
        else:
            next(block for block in project.candidates[0].blocks if block.type == "detect").params["model"] = "different-model"
        service.repository.save(project)
    elif change == "labels":
        dataset = service.annotations(project_id)
        dataset.annotations[0].reviewed = False
        service.save_annotations(project_id, dataset)
    elif change == "pixels":
        from PIL import Image
        path = service.root(project_id) / service.annotations(project_id).annotations[0].image_path
        image = Image.open(path).convert("RGB")
        image.putpixel((0, 0), (12, 34, 56))
        image.save(path)
    elif change == "settings":
        settings = service.repository.settings()
        settings.planner_model = "changed-model"
        service.repository.save_settings(settings)
    else:
        (service.root(project_id) / "zones" / "changed.json").write_text('{"zones":[]}')
    with pytest.raises(AgentConflict, match="stale"):
        platform.authorize(project_id, execution.operation_id, Phase.COMPILE, "pipeline_validate",
                           {"project_id": project_id, "spec": candidate.model_dump(mode="json", by_alias=True)})
    assert platform.execution(project_id, execution.operation_id).status == "stale"  # type: ignore[union-attr]
    assert platform.plan(project_id, plan.id) == plan
    assert not platform.events(project_id)


def test_execution_rejects_unplanned_graph_and_phase_tool(tmp_path: Path) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    platform = PlatformStore(service)
    _, execution = platform.publish(project_id, "2" * 32, "Count pallets", [candidate], Phase.COMPILE, "test")
    changed = candidate.model_copy(deep=True)
    changed.eval.target = 25
    with pytest.raises(AgentConflict, match="differs"):
        platform.authorize(project_id, execution.operation_id, Phase.COMPILE, "pipeline_run",
                           {"project_id": project_id, "spec": changed.model_dump(mode="json", by_alias=True)})
    with pytest.raises(AgentConflict, match="phase authority"):
        platform.authorize(project_id, execution.operation_id, Phase.COMPILE, "build_operate", {"project_id": project_id})


async def test_real_executor_consumes_saved_plan_and_replay_has_no_duplicate_effects(tmp_path: Path) -> None:
    service, project_id, candidate, decision = fixture(tmp_path)
    build = BuildStore(service).create(project_id, "Count pallets")
    state = AgentStateStore(service)
    result = compile_decision(decision, "media", "fixture-color-v1")
    async with connect_tools(str(tmp_path), AgentState()) as tools:
        await tools.start_run(project_id, "Count pallets", "media", "fixture-color-v1")
        await tools.control("agent_record_decision", {"decision": decision.model_dump(mode="json")})
        await execute_candidates(tools, result, "media", "fixture-color-v1")
        result.operation_id, result.tool_calls = tools.operation_id, tools.state.budget.tool_calls
        await tools.control("agent_stage_plan", {"result": result.model_dump(mode="json", by_alias=True)})
    state.commit_plan(project_id, result.operation_id, result, "Count pallets")
    view = BuildStore(service).public(BuildStore(service).get(project_id, build.view.id))
    assert view.plan and view.plan.candidates == [candidate]
    assert view.execution and view.execution.plan_id == view.plan.id
    assert [(event.name, event.stage) for event in view.tool_events] == [
        ("pipeline_validate", "started"), ("pipeline_validate", "completed"),
        ("pipeline_run", "started"), ("pipeline_run", "completed")]
    assert view.plan.created_at <= view.tool_events[0].at
    before = service.get_project(project_id).model_dump_json(), service.annotations(project_id).model_dump_json()
    replay = state.platform.replay(project_id, view.execution.id)
    assert replay.dry_run and not replay.effects_executed
    assert any(artifact.kind == "preview" for artifact in replay.artifacts)
    preview_event = replay.events[-1]
    assert preview_event.output_artifact_id
    assert len(state.platform.artifact_content(project_id, preview_event.output_artifact_id).content["frames"]) == 5  # type: ignore[arg-type]
    assert before == (service.get_project(project_id).model_dump_json(), service.annotations(project_id).model_dump_json())
    assert not service.events(project_id)


def test_new_plan_revision_preserves_prior_artifact_and_changed_goal(tmp_path: Path) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    platform = PlatformStore(service)
    first, old_run = platform.publish(project_id, "3" * 32, "Count pallets", [candidate], Phase.COMPILE, "initial")
    changed = candidate.model_copy(deep=True)
    changed.eval.target = .1
    second, _ = platform.publish(project_id, "3" * 32, "Lower count error", [changed], Phase.EVALUATE, "explicit revised target")
    assert second.revision == first.revision + 1 and second.parent_plan_id == first.id
    assert first.content_hash != second.content_hash and platform.plan(project_id, first.id) == first
    replay = platform.replay(project_id, old_run.id)
    assert replay.execution.status == "stale" and "Superseded" in (replay.execution.error or "")
    assert not replay.events


@pytest.mark.parametrize("change", ["bridge", "os"])
def test_reading_plan_binds_native_bridge_and_os_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    from agent.templates import build_template
    service, project_id, _, _ = fixture(tmp_path)
    bridge = tmp_path / "test-bridge"
    bridge.write_bytes(b"not executable; identity test only")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    platform = PlatformStore(service)
    before = platform.snapshot(project_id, [candidate])
    if change == "bridge":
        bridge.write_bytes(b"replacement bridge")
    else:
        monkeypatch.setattr("engine.platform.store.platform.mac_ver", lambda: ("changed OS", (), ""))
    assert platform.snapshot(project_id, [candidate]).model_hashes != before.model_hashes


def test_skill_edit_between_planning_and_execution_requires_reinterpretation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.skills as skills
    service, project_id, _, decision = fixture(tmp_path)
    state = AgentStateStore(service)
    operation = state.begin(project_id, "Count pallets", "media", "fixture-color-v1")
    selected = select_skills("Count pallets")
    state.record_skills(project_id, operation.id, [skill.reference for skill in selected])
    state.record_decision(project_id, operation.id, decision)
    altered = [skill.reference.model_copy(update={"sha256": "0" * 64}) for skill in selected]
    with pytest.raises(AgentConflict, match="Skill references"):
        state.record_skills(project_id, operation.id, altered)
    monkeypatch.setattr(skills, "select_skills", lambda *args: ())
    with pytest.raises(AgentConflict, match="Skill references"):
        state.prepare_compile(project_id, operation.id, 1)
    assert not state.platform.plans(project_id)


def test_interrupted_action_finishes_once_without_reexecution(tmp_path: Path) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    service.save_candidates(project_id, [candidate], "Count pallets")
    builds = BuildStore(service)
    record = builds.create(project_id, "Evaluate pallets")
    record.operation.state.phase = Phase.EVALUATE
    builds.save(record)
    call = builds.start_call(project_id, record.view.id, "eval_run", {"project_id": project_id, "candidate_index": 0})
    record = builds.get(project_id)
    record.operation.deadline = time() - 1
    builds.save(record)
    assert builds.get(project_id).view.status == "interrupted"
    events = builds.platform.events(project_id)
    assert [(event.call_id, event.stage) for event in events] == [(call.id, "started"), (call.id, "interrupted")]
    builds.get(project_id)
    assert builds.platform.events(project_id) == events
    assert not service.get_project(project_id).evaluations


async def test_refinement_plan_exists_inside_real_preview_and_reports_actual_evaluations(tmp_path: Path) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    service.save_candidates(project_id, [candidate], "Count pallets")
    manager = BuildManager(service)
    try:
        await manager.start(project_id, "Set confidence to 0.5")
        await manager.tasks[project_id]
        view = manager.status(project_id)
        assert view.status in {"awaiting_review", "awaiting_improvement"}, view.message
        assert view.plan and view.execution
        events = view.tool_events
        refine = next(event for event in events if event.name == "build_refine" and event.stage == "started")
        assert refine.plan_id and manager.store.platform.plan(project_id, refine.plan_id).created_at <= refine.at
        assert any(event.name == "eval_run" and event.stage == "completed" for event in events)
        reports = list((manager.store.platform.root(project_id) / "evaluations").glob("*.json"))
        assert reports and json.loads(reports[0].read_text())["spec_hash"] == view.evaluations[0].spec_hash
        report = json.loads(reports[0].read_text())
        assert report["protocol_id"] == view.evaluations[0].protocol_id
        assert report["promotion_eligible"] is False and report["evidence_scope"] == "sample"
        assert not service.events(project_id) and not (service.root(project_id) / "deployment.json").exists()
    finally:
        await manager.close()


def test_public_read_routes_return_same_events_and_do_not_execute(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from engine.api.build_routes import build_router
    service, project_id, candidate, _ = fixture(tmp_path)
    service.save_candidates(project_id, [candidate], "Count pallets")
    manager = BuildManager(service)
    record = manager.store.create(project_id, "Evaluate pallets")
    record.operation.state.phase = Phase.EVALUATE
    manager.store.save(record)
    call = manager.store.start_call(project_id, record.view.id, "eval_run", {"project_id": project_id})
    result = service.evaluate(project_id)
    manager.store.finish_call(project_id, record.view.id, call.id, result.model_dump(mode="json"))
    before = service.get_project(project_id).model_dump_json()
    app = FastAPI()
    app.include_router(build_router(service, manager))
    with TestClient(app) as client:
        status = client.get(f"/projects/{project_id}/build").json()
        assert client.get(f"/projects/{project_id}/build/plan").json() == status["plan"]
        assert client.get(f"/projects/{project_id}/build/events").json() == status["tool_events"]
        artifacts = client.get(f"/projects/{project_id}/build/artifacts").json()
        assert len(artifacts) == 2
        for artifact in artifacts:
            response = client.get(f"/projects/{project_id}/build/artifacts/{artifact['id']}")
            assert response.status_code == 200 and response.json()["artifact"] == artifact
        replay = client.get(f"/projects/{project_id}/build/replay").json()
        assert replay["effects_executed"] is False and len(replay["evaluations"]) == 1
        assert replay["evaluations"][0]["metrics"]["character_error_rate"] is None
    assert service.get_project(project_id).model_dump_json() == before and not service.events(project_id)


def test_hash_tampering_is_rejected_for_plan_and_artifact(tmp_path: Path) -> None:
    service, project_id, candidate, _ = fixture(tmp_path)
    platform = PlatformStore(service)
    plan, _ = platform.publish(project_id, "4" * 32, "Count pallets", [candidate], Phase.COMPILE, "test")
    path = platform.path(project_id, "plans", plan.id)
    changed = json.loads(path.read_text())
    changed["goal"] = "Tampered goal"
    path.write_text(json.dumps(changed))
    with pytest.raises(AgentConflict, match="content hash"):
        platform.plan(project_id, plan.id)
    artifact = platform.artifact(project_id, "tool_output", "Actual fixture result", {"valid": True})
    path = platform.path(project_id, "artifacts", artifact.id)
    changed = json.loads(path.read_text())
    changed["content"]["valid"] = False
    path.write_text(json.dumps(changed))
    with pytest.raises(AgentConflict, match="content hash"):
        platform.artifact_content(project_id, artifact.id)


@pytest.mark.parametrize("boundary", ["initial", "build"])
def test_concurrent_action_cannot_replace_inflight_execution(tmp_path: Path, boundary: str) -> None:
    service, project_id, candidate, decision = fixture(tmp_path)
    if boundary == "initial":
        state = AgentStateStore(service)
        operation = state.begin(project_id, "Count pallets", "media", "fixture-color-v1")
        state.record_decision(project_id, operation.id, decision)
        state.prepare_compile(project_id, operation.id, 1)
        arguments = {"project_id": project_id, "spec": candidate.model_dump(mode="json", by_alias=True)}
        state.start_call(project_id, operation.id, "tool", "pipeline_validate", arguments)
        with pytest.raises(AgentConflict, match="already in progress"):
            state.start_call(project_id, operation.id, "tool", "pipeline_run", arguments)
        assert len(state.platform.plans(project_id)) == 1
    else:
        service.save_candidates(project_id, [candidate], "Count pallets")
        store = BuildStore(service)
        record = store.create(project_id, "Evaluate pallets")
        record.operation.state.phase = Phase.EVALUATE
        store.save(record)
        store.start_call(project_id, record.view.id, "eval_run", {"project_id": project_id})
        with pytest.raises(AgentConflict, match="already in progress"):
            store.start_call(project_id, record.view.id, "pipeline_run", {"project_id": project_id})
        assert len(store.platform.plans(project_id)) == 1


def test_context_guard_counts_system_guidance_and_schema() -> None:
    from agent.planner import PlannerError, check_context_size
    check_context_size("small system", "small request", {"type": "object"})
    with pytest.raises(PlannerError, match="playbooks"):
        check_context_size("s" * 15000, "u" * 5000, {"schema": "x" * 5000})
