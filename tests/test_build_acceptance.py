"""Acceptance boundaries for the agent-led describe → preview → review workflow."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.build_orchestrator import select_candidate
from agent.templates import build_template
from engine.eval import evaluate
from engine.service import WorkspaceService


def reviewed_workspace(root: Path) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(root)
    project = service.create_project("Agent acceptance fixture", "custom")
    service.demo(project.id)
    return service, project.id


@pytest.mark.parametrize("metric,target", [("count_mae", .5), ("recall", .8), ("precision", .8)])
def test_agent_selects_measured_winner_in_metric_direction(tmp_path: Path, metric: str, target: float) -> None:
    service, project_id = reviewed_workspace(tmp_path)
    good = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    good.eval = type(good.eval)(metric=metric, target=target)
    bad = good.model_copy(deep=True)
    bad.name = "First candidate misses every object"
    for block in bad.blocks:
        if block.type in {"detect", "detect_open_vocab"}:
            block.params["min_conf"] = 1.0
    service.save_candidates(project_id, [bad, good], "Compare fixture thresholds")
    protocol = service.freeze_evaluation(project_id)
    results = [service.evaluate(project_id, index, protocol.id) for index in range(2)]
    assert not results[0].passed and results[1].passed
    assert select_candidate(results) == 1
    assert select_candidate(list(reversed(results))) == 0


@pytest.mark.parametrize("change", ["metric", "target", "dataset_hash"])
def test_agent_refuses_incomparable_candidate_evidence(tmp_path: Path, change: str) -> None:
    service, project_id = reviewed_workspace(tmp_path)
    spec = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    first = evaluate(spec, service.annotations(project_id), service.root(project_id))
    second = first.model_copy(deep=True)
    if change == "metric":
        second.metric = "count_mae" if first.metric != "count_mae" else "recall"
    elif change == "target":
        second.target = 100
    else:
        second.dataset_hash = "different-reviewed-holdout"
    with pytest.raises(ValueError):
        select_candidate([first, second])


def staged_plan(service: WorkspaceService, project_id: str, brief: str, decision: object) -> object:
    """Stub only language generation; compile and preview actual fixture pixels."""
    from agent.contracts import PlanDecision
    from agent.decisions import compile_decision
    from engine.agent_state import AgentStateStore
    from engine.compiler import compile_pipeline
    from engine.runtime import run_pipeline
    assert isinstance(decision, PlanDecision)
    store = AgentStateStore(service)
    operation = store.begin(project_id, brief, "media", "fixture-color-v1")
    call = store.start_call(project_id, operation.id, "llm", "deterministic-test-decision", {"prompt": brief})
    store.finish_call(project_id, operation.id, call.id, {"decision": decision.model_dump(mode="json")})
    store.record_decision(project_id, operation.id, decision)
    result = compile_decision(decision, "media", "fixture-color-v1")
    if result.candidates:
        store.prepare_compile(project_id, operation.id, len(result.candidates))
    for candidate in result.candidates:
        payload = {"project_id": project_id, "spec": candidate.model_dump(mode="json", by_alias=True)}
        call = store.start_call(project_id, operation.id, "tool", "pipeline_validate", payload)
        compile_pipeline(candidate, service.root(project_id))
        store.finish_call(project_id, operation.id, call.id, {"valid": True, "errors": []})
        call = store.start_call(project_id, operation.id, "tool", "pipeline_run", payload)
        result_pixels = run_pipeline(candidate, service.root(project_id), max_frames=5)
        store.finish_call(project_id, operation.id, call.id, result_pixels.model_dump(mode="json"))
    result.operation_id = operation.id
    result.tool_calls = store.operation(project_id, operation.id).state.budget.tool_calls
    store.stage(project_id, operation.id, result)
    return result


async def finish_build(manager: object, project_id: str) -> object:
    import asyncio

    from engine.builds.manager import BuildManager
    assert isinstance(manager, BuildManager)
    task = manager.tasks.get(project_id)
    if task is not None:
        await asyncio.wait_for(task, timeout=40)
    return manager.status(project_id)


def choices(metric: str = "count_mae") -> object:
    from agent.contracts import PatternChoice, PlanDecision
    return PlanDecision(message="Compare two measured detector thresholds", choices=[
        PatternChoice(use_case="custom", objects=["pallet"], min_confidence=confidence,
                      metric=metric, target=.5 if metric == "count_mae" else .8)
        for confidence in (1.0, .2)])


async def test_description_without_media_returns_actionable_attach_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.builds.manager as module
    service = WorkspaceService(tmp_path)
    project = service.create_project("No folders required", "custom")
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No-image build should request media before calling a planner")
    monkeypatch.setattr(module, "agent_plan", forbidden)
    manager = module.BuildManager(service)
    try:
        status = await manager.start(project.id, "Count people and show boxes")
        assert status.next_action == "attach_media" and status.preview is None
        assert service.get_project(project.id).candidates == []
        assert manager.store.get(project.id).prompt == "Count people and show boxes"
    finally:
        await manager.close()


@pytest.mark.parametrize("metric", ["count_mae", "recall"])
async def test_agent_build_evaluates_every_candidate_and_waits_for_human_deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metric: str,
) -> None:
    import engine.builds.manager as module
    from spec.build import BuildContinueRequest, BuildStatus
    service, project_id = reviewed_workspace(tmp_path)
    original_labels = service.annotations(project_id)
    async def deterministic_plan(brief: str, source: str, settings: object) -> object:
        assert source == "media"
        return staged_plan(service, project_id, brief, choices(metric))
    monkeypatch.setattr(module, "agent_plan", deterministic_plan)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Count pallets and show bounding boxes")
        status = await finish_build(manager, project_id)
        assert isinstance(status, BuildStatus)
        assert status.status == "awaiting_review", status.message
        assert status.next_action == "configure_evaluation" and status.selected_candidate_index == 1
        assert len(status.evaluations) == 2 and not status.evaluations[0].passed and status.evaluations[1].passed
        assert status.preview and status.preview.frames and status.preview.frames[0].detections
        assert all(Path(frame.image_path).is_file() for frame in status.preview.frames)
        calls = manager.store.get(project_id).operation.calls
        evaluations = [call for call in calls if call.name == "eval_run" and call.status == "completed"]
        assert [call.request["candidate_index"] for call in evaluations] == [0, 1]
        assert service.annotations(project_id) == original_labels
        assert service.get_project(project_id).deployment_id is None and not service.events(project_id)
        waiting = await manager.continue_build(project_id, BuildContinueRequest())
        assert waiting.status in {"running", "awaiting_review"} and not service.events(project_id)
        await finish_build(manager, project_id)
        # Explicit approval in this isolated geometric test is the only action
        # that may authorize persisted operation; the agent never supplies it.
        service.deploy(project_id, 1, True, "Isolated synthetic software trial", approval_scope="local_trial")
        await manager.continue_build(project_id, BuildContinueRequest())
        completed = await finish_build(manager, project_id)
        assert isinstance(completed, BuildStatus) and completed.status == "completed", completed
        assert service.events(project_id)
        count = len(service.events(project_id))
        await manager.continue_build(project_id, BuildContinueRequest())
        assert len(service.events(project_id)) == count
    finally:
        await manager.close()


async def test_review_flags_and_manual_boxes_survive_agent_build_and_review_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.builds.manager as module
    from spec.build import BuildContinueRequest, BuildStatus
    service, project_id = reviewed_workspace(tmp_path)
    labels = service.annotations(project_id)
    labels.annotations[-1].reviewed = False
    service.save_annotations(project_id, labels)
    before = service.annotations(project_id)
    async def deterministic_plan(brief: str, source: str, settings: object) -> object:
        return staged_plan(service, project_id, brief, choices())
    monkeypatch.setattr(module, "agent_plan", deterministic_plan)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Count pallets in these samples")
        status = await finish_build(manager, project_id)
        assert isinstance(status, BuildStatus) and status.status == "awaiting_review", status
        assert status.next_action == "review_labels" and status.preview and not status.evaluations
        assert service.annotations(project_id) == before
        assert not service.get_project(project_id).evaluations and service.get_project(project_id).deployment_id is None
        # The human action reviews existing boxes without rebuilding the graph.
        reviewed = service.annotations(project_id)
        reviewed.annotations[-1].reviewed = True
        service.save_annotations(project_id, reviewed)
        await manager.continue_build(project_id, BuildContinueRequest())
        resumed = await finish_build(manager, project_id)
        assert isinstance(resumed, BuildStatus) and resumed.status == "awaiting_review", resumed
        assert len(resumed.evaluations) == 2 and service.annotations(project_id) == reviewed
    finally:
        await manager.close()


async def test_planner_failure_cannot_claim_a_preview_or_evaluation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.builds.manager as module
    from agent.planner import PlannerError
    from spec.build import BuildStatus
    service, project_id = reviewed_workspace(tmp_path)
    async def offline(*args: object, **kwargs: object) -> None:
        raise PlannerError("Local model unavailable in this deliberate acceptance test")
    monkeypatch.setattr(module, "agent_plan", offline)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Count pallets")
        status = await finish_build(manager, project_id)
        assert isinstance(status, BuildStatus) and status.status == "failed", status
        assert status.preview is None and status.evaluations == []
        assert not manager.store.get(project_id).operation.calls
        assert not service.get_project(project_id).candidates and not service.events(project_id)
        assert "unavailable" in status.message.lower()
    finally:
        await manager.close()


async def test_confidence_followup_edits_selected_winner_through_mcp_without_rebuilding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.builds.manager as module
    from spec.build import BuildStatus
    service, project_id = reviewed_workspace(tmp_path)
    requests = []
    async def deterministic_plan(brief: str, source: str, settings: object) -> object:
        requests.append(brief)
        return staged_plan(service, project_id, brief, choices())
    monkeypatch.setattr(module, "agent_plan", deterministic_plan)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Count pallets and show boxes")
        first = await finish_build(manager, project_id)
        assert isinstance(first, BuildStatus) and first.selected_candidate_index == 1
        originals = [candidate.model_copy(deep=True) for candidate in service.get_project(project_id).candidates]
        labels = service.annotations(project_id)
        expected = originals[1].model_copy(deep=True)
        next(block for block in expected.blocks if block.type == "detect").params["min_conf"] = .5
        await manager.start(project_id, "raise confidence to0.5")
        changed = await finish_build(manager, project_id)
        assert isinstance(changed, BuildStatus) and changed.status == "awaiting_review", changed
        assert len(requests) == 1, "A bounded explicit edit should not regenerate the existing graph"
        assert service.candidate(project_id, 0) == originals[0] and service.candidate(project_id, 1) == expected
        assert service.annotations(project_id) == labels
        calls = manager.store.get(project_id).operation.calls
        refinement = next(call for call in calls if call.name == "build_refine")
        assert refinement.status == "completed" and refinement.result and refinement.result["preview"]
        assert changed.preview and changed.preview.frames[0].detections
        assert service.get_project(project_id).deployment_id is None
    finally:
        await manager.close()


async def test_new_class_followup_requires_fresh_human_review_before_continue_can_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.builds.manager as module
    from spec.build import BuildContinueRequest, BuildStatus
    service, project_id = reviewed_workspace(tmp_path)
    original = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    service.save_candidates(project_id, [original], "Count pallets")
    original_labels = service.annotations(project_id)
    assert all(row.reviewed for row in original_labels.annotations)
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Explicit additive refinement must preserve the existing graph")
    monkeypatch.setattr(module, "agent_plan", forbidden)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "also detect cartons")
        status = await finish_build(manager, project_id)
        assert isinstance(status, BuildStatus) and status.status == "awaiting_review", status
        revised = service.annotations(project_id)
        assert not any(row.reviewed for row in revised.annotations)
        assert [row.detections for row in revised.annotations] == [row.detections for row in original_labels.annotations]
        assert [row.proposal for row in revised.annotations] == [row.proposal for row in original_labels.annotations]
        await manager.continue_build(project_id, BuildContinueRequest())
        paused = await finish_build(manager, project_id)
        assert isinstance(paused, BuildStatus) and paused.status == "awaiting_review", paused
        assert paused.evaluations == [] and not service.get_project(project_id).evaluations
        assert not any(call.name == "eval_run" for call in manager.store.get(project_id).operation.calls)
    finally:
        await manager.close()


@pytest.mark.parametrize("scope_change", ["classes", "zones"])
async def test_alternatives_with_different_goal_scopes_cannot_select_an_old_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope_change: str,
) -> None:
    import engine.builds.manager as module
    from spec.build import BuildStatus
    from spec.models import BlockSpec
    service, project_id = reviewed_workspace(tmp_path)
    async def deterministic_plan(brief: str, source: str, settings: object) -> object:
        return staged_plan(service, project_id, brief, choices())
    monkeypatch.setattr(module, "agent_plan", deterministic_plan)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Count pallets")
        original = await finish_build(manager, project_id)
        assert isinstance(original, BuildStatus) and original.selected_candidate_index == 1
        if scope_change == "classes":
            from engine.builds.refinement import refine_app
            from spec.refinement import RefinementPatch
            # Deliberately target one alternative; ordinary goal changes apply to all.
            refine_app(service, project_id, RefinementPatch(kind="add_classes", classes=["carton"],
                       scope="selected"), candidate_index=1)
            # Explicit isolated-fixture review: no cartons exist in this generated set.
            labels = service.annotations(project_id)
            for row in labels.annotations:
                row.reviewed = True
            service.save_annotations(project_id, labels)
            expected = [row.model_copy(deep=True) for row in service.get_project(project_id).candidates]
            next(block for block in expected[1].blocks if block.type == "detect").params["min_conf"] = .5
            await manager.start(project_id, "raise confidence to0.5")
        else:
            before = service.candidate(project_id, 1)
            scoped = before.model_copy(deep=True)
            scoped.blocks.append(BlockSpec(id="left_scope", type="zone_filter",
                params={"zones": [{"id": "left", "polygon": [[0, 0], [.5, 0], [.5, 1], [0, 1]]}]},
                inputs={"dets": "$det.dets"}))
            next(block for block in scoped.blocks if block.type == "count_per_zone").inputs["dets"] = "$left_scope.dets"
            service.update_candidate(project_id, 1, scoped, before)
            expected = [row.model_copy(deep=True) for row in service.get_project(project_id).candidates]
            next(block for block in expected[1].blocks if block.type == "detect").params["min_conf"] = .5
            await manager.start(project_id, "raise confidence to0.5")
        paused = await finish_build(manager, project_id)
        assert isinstance(paused, BuildStatus)
        assert paused.status == "awaiting_clarification" and paused.phase == "clarifying_scope", paused
        assert "different" in paused.message.lower() and ("scope" in paused.message.lower() or "zones" in paused.message.lower())
        assert service.get_project(project_id).candidates == expected
        assert paused.evaluations == [] and not service.get_project(project_id).evaluations
        assert service.get_project(project_id).deployment_id is None and not service.events(project_id)
        assert not any(call.name == "eval_run" for call in manager.store.get(project_id).operation.calls)
    finally:
        await manager.close()
