"""Typed refinement interpretation and human checkpoints, separate from LLM quality."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.machine import AgentConflict
from agent.planner import PlannerError
from agent.refinement import interpret_refinement
from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
from agent.templates import build_template
from engine.builds.manager import BuildManager
from engine.builds.store import BuildStore
from engine.service import WorkspaceService
from engine.zones import save_zone_state
from spec.build import BuildContinueRequest
from spec.models import PipelineSpec, Zone
from spec.refinement import RefinementContext, RefinementPatch


def app(root: Path) -> tuple[WorkspaceService, str, PipelineSpec]:
    service = WorkspaceService(root)
    project = service.create_project("Isolated refinement fixture", "custom")
    service.demo(project.id)
    candidate = build_template("pallets", "media", "fixture-color-v1")[0]
    service.save_candidates(project.id, [candidate], "Count pallets by lane")
    return service, project.id, candidate


def capture(store: BuildStore, project_id: str, build_id: str, decision: RefinementDecision) -> None:
    call = store.start_model_call(project_id, build_id, "deterministic-test-refinement", {"purpose": "transport fixture, not language quality"})
    store.finish_call(project_id, build_id, call.id, {"decision": decision.model_dump(mode="json")})
    store.record_refinement_decision(project_id, build_id, decision.model_dump(mode="json"))


def test_decision_requires_one_outcome_and_rejects_unrequested_destructive_or_selected_edits() -> None:
    candidate = build_template("custom", "media", "fixture-color-v1", classes=["person", "forklift"])[0]
    context = RefinementContext(candidates=[candidate], selected_candidate_index=0, current_goal="Count objects", conversation=[],
                                classes=["person", "forklift"], saved_zone_ids=[], clarification_count=0)
    for questions, patches in [([], []), (["Which count?"], [RefinementPatch(kind="confidence", confidence=.5)])]:
        with pytest.raises(ValidationError):
            RefinementDecision(message="invalid", questions=questions, patches=patches)
    removed = RefinementDecision(message="remove", questions=[], patches=[RefinementPatch(kind="remove_classes", classes=["person"])])
    with pytest.raises(ValueError, match="explicit"):
        validate_refinement_intent(removed, "also detect boxes", context)
    validate_refinement_intent(removed, "stop detecting person", context)
    selected = RefinementDecision(message="edit", questions=[], patches=[RefinementPatch(kind="sample_fps", fps=.5, scope="selected")])
    with pytest.raises(ValueError, match="all alternatives"):
        validate_refinement_intent(selected, "sample every two seconds", context)


def test_decision_must_match_actual_captured_response(tmp_path: Path) -> None:
    service, project_id, _ = app(tmp_path)
    store = BuildStore(service)
    record = store.create(project_id, "Use seventy percent confidence")
    decision = RefinementDecision(message="change", questions=[], patches=[RefinementPatch(kind="confidence", confidence=.7)])
    with pytest.raises(AgentConflict, match="captured"):
        store.record_refinement_decision(project_id, record.view.id, decision.model_dump(mode="json"))
    capture(store, project_id, record.view.id, decision)
    decision.patches[0].confidence = .1
    with pytest.raises(AgentConflict, match="differs"):
        store.record_refinement_decision(project_id, record.view.id, decision.model_dump(mode="json"))


async def test_contextual_answer_preserves_original_request_and_actual_question(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.builds.manager as module
    service, project_id, original = app(tmp_path)
    manager = BuildManager(service)
    prompts = []
    async def interpreter(prompt: str, settings: object, build_id: str, candidate_index: int = 0) -> RefinementDecision:
        prompts.append(prompt)
        if len(prompts) == 1:
            decision = RefinementDecision(message="Need threshold", questions=["At what object count should the alert trigger?"], patches=[])
        else:
            assert service.get_project(project_id).messages[-1].content == "At what object count should the alert trigger?"
            decision = RefinementDecision(message="Use four objects", questions=[], patches=[RefinementPatch(kind="count_rule", count_threshold=4)])
        capture(manager.store, project_id, build_id, decision)
        return decision
    monkeypatch.setattr(module, "interpret_refinement", interpreter)
    try:
        await manager.start(project_id, "Change when the lane alert triggers")
        await manager.tasks[project_id]
        first = manager.status(project_id)
        assert first.status == "awaiting_clarification" and service.candidate(project_id, 0) == original
        await manager.continue_build(project_id, BuildContinueRequest(prompt="At four pallets"))
        await manager.tasks[project_id]
        second = manager.status(project_id)
        assert second.status == "awaiting_approval", second.message
        assert prompts == ["Change when the lane alert triggers", "Change when the lane alert triggers\nUser clarification: At four pallets"]
        changed = service.candidate(project_id, 0)
        assert next(block for block in changed.blocks if block.type == "rule").params["when"] == "count >= 4.0"
        assert len([call for call in manager.store.get(project_id).operation.calls if call.kind == "llm"]) == 2
        assert service.get_project(project_id).clarification_count == 1 and not service.events(project_id)
    finally:
        await manager.close()


async def test_missing_local_model_preserves_graph_and_has_no_silent_parser_fallback(tmp_path: Path) -> None:
    service, project_id, original = app(tmp_path)
    store = BuildStore(service)
    record = store.create(project_id, "set confidence to .5")
    with pytest.raises(PlannerError, match="unavailable"):
        await interpret_refinement(record.prompt, {"project_id": project_id, "mcp_data_dir": str(tmp_path),
            "model_url": "http://127.0.0.1:1/v1", "planner_model": "absent"}, record.view.id)
    assert service.candidate(project_id, 0) == original
    assert not store.get(project_id).refinement_decisions
    assert not any(call.name == "build_refine" for call in store.get(project_id).operation.calls)


async def test_zone_checkpoint_requires_saved_geometry_and_replans_original_goal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Define dock regions", "custom")
    manager = BuildManager(service)
    record = manager.store.create(project.id, "Count people in dock 4")
    record.view.phase = "awaiting_zones"
    manager.store.pause(record, "awaiting_review", "define_zones", "Draw dock 4 on your image")
    pending = await manager.continue_build(project.id, BuildContinueRequest())
    assert pending.next_action == "define_zones" and project.id not in manager.tasks
    save_zone_state(service.root(project.id), [Zone(id="dock 4", polygon=[[0, 0], [1, 0], [1, 1], [0, 1]])])
    seen = []
    async def plan(project_id: str, build_id: str) -> None:
        active = manager.store.get(project_id, build_id)
        manager.store.assert_current(active)
        seen.append(active.prompt)
        manager.store.pause(active, "awaiting_review", "review_labels", "Isolated checkpoint test")
    monkeypatch.setattr(manager, "_plan", plan)
    try:
        await manager.continue_build(project.id, BuildContinueRequest())
        await manager.tasks[project.id]
        assert seen == ["Count people in dock 4"]
        assert service.get_project(project.id).clarification_count == 0
    finally:
        await manager.close()


async def test_explicit_human_override_resumes_missed_target_to_run(tmp_path: Path) -> None:
    service, project_id, original = app(tmp_path)
    bad = original.model_copy(deep=True)
    next(block for block in bad.blocks if block.type == "detect").params["min_conf"] = 1.0
    service.save_candidates(project_id, [bad], "Count pallets")
    result = service.evaluate(project_id, 0)
    assert not result.passed
    manager = BuildManager(service)
    record = manager.store.create(project_id, "Count pallets")
    preview = service.preview(project_id, 0)
    manager._scored(project_id, record.view.id, [result], 0, preview)
    assert manager.status(project_id).status == "awaiting_improvement"
    service.deploy(project_id, 0, approved=True, override_reason="Isolated synthetic fixture deployment test")
    try:
        await manager.continue_build(project_id, BuildContinueRequest())
        await manager.tasks[project_id]
        status = manager.status(project_id)
        assert status.status == "completed", status.message
        calls = manager.store.get(project_id).operation.calls
        assert any(call.name == "build_operate" and call.status == "completed" for call in calls)
        assert not any(call.name in {"eval_run", "build_train"} for call in calls)
    finally:
        await manager.close()


@pytest.mark.parametrize("prompt,patch", [
    ("Change the alert threshold", RefinementPatch(kind="confidence", confidence=.7)),
    ("Change the count threshold to four", RefinementPatch(kind="confidence", confidence=.7)),
    ("Instead of pallets look only for forklifts", RefinementPatch(kind="replace_classes", classes=["pallet"])),
    ("Stop detecting pallets; keep the forklifts", RefinementPatch(kind="replace_classes", classes=["pallet"])),
    ("At least five forklifts should trigger an event", RefinementPatch(kind="count_rule", count_threshold=5)),
    ("Set candidate 2 confidence to .5", RefinementPatch(kind="confidence", confidence=.5)),
])
def test_semantic_guards_reject_known_wrong_interpretations(prompt: str, patch: RefinementPatch) -> None:
    candidate = build_template("pallets", "media", "fixture-color-v1")[0]
    next(block for block in candidate.blocks if block.type == "detect").params["classes"] = ["pallet", "forklift"]
    context = RefinementContext(candidates=[candidate, candidate], selected_candidate_index=0, current_goal="Count pallets and forklifts",
        conversation=[], classes=["pallet", "forklift"], saved_zone_ids=[], clarification_count=0)
    decision = RefinementDecision(message="Rejected interpretation", questions=[], patches=[patch])
    with pytest.raises(ValueError):
        validate_refinement_intent(decision, prompt, context)


def test_model_schema_excludes_cross_kind_fields() -> None:
    from agent.refinement_output import RefinementModelDecision
    with pytest.raises(ValidationError, match="Extra inputs"):
        RefinementModelDecision.model_validate({"message": "replace", "questions": [], "patches": [
            {"kind": "replace_classes", "classes": ["forklift"], "expected_text": "forklift"}]})
    decision = RefinementModelDecision.model_validate({"message": "replace", "questions": [], "patches": [
        {"kind": "replace_classes", "classes": ["forklift"]}]}).normalized()
    assert decision.patches == [RefinementPatch(kind="replace_classes", classes=["forklift"])]


async def test_cancelled_model_attempt_records_failure() -> None:
    import asyncio
    from types import SimpleNamespace

    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.models.function import FunctionModel

    from agent.recording import RecordedModel
    captured = []
    class Tools:
        async def capture_start(self, *args: object) -> SimpleNamespace:
            return SimpleNamespace(id="cancelled-call")
        async def capture_finish(self, *args: object) -> None:
            captured.append(args)
    async def cancel(*args: object) -> object:
        raise asyncio.CancelledError()
    model = RecordedModel(FunctionModel(cancel), Tools())
    with pytest.raises(asyncio.CancelledError):
        await model.request([], None, ModelRequestParameters())
    assert captured == [("cancelled-call", None, "Local model request was cancelled")]


@pytest.mark.parametrize("behavior", ["rule", "match"])
async def test_candidate_comparison_rejects_different_event_behavior(tmp_path: Path, behavior: str) -> None:
    from agent.machine import AgentState, Phase
    from agent.mcp_client import connect_tools
    from spec.build import BuildContext
    service, project_id, first = app(tmp_path)
    if behavior == "match":
        first = build_template("labels", "media", "fixture-color-v1")[0]
    second = first.model_copy(deep=True)
    block = next(block for block in second.blocks if block.type == behavior)
    block.params["hold_s" if behavior == "rule" else "expected"] = 30 if behavior == "rule" else "DIFFERENT-TEXT"
    service.save_candidates(project_id, [first, second], "Deliberately divergent alternatives")
    store = BuildStore(service)
    record = store.create(project_id, "Review these candidates")
    record.operation.state.phase = Phase.EVALUATE
    store.save(record)
    async with connect_tools(str(tmp_path), AgentState()) as tools:
        await tools.bind_build(project_id, record.view.id)
        context = BuildContext.model_validate(await tools.call("build_context", {"project_id": project_id}))
    assert len(set(context.comparison_scopes)) == 2
    assert service.get_project(project_id).candidates == [first, second]


@pytest.mark.parametrize("prompt,fps", [
    ("Check just one frame every two seconds.", .5), ("one frame every 2s", .5),
    ("a frame every half minute", 1 / 30), ("frame every 500 ms", 2),
    ("Process five frames a second", 5), (".5 fps", .5),
    ("Switch from two frames a second to one frame every four seconds", .25),
])
def test_explicit_sampling_units_are_checked_dimensionally(prompt: str, fps: float) -> None:
    from agent.refinement_fidelity import explicit_sampling_fps
    assert explicit_sampling_fps(prompt) == pytest.approx(fps)


def test_explicit_fidelity_rejects_silent_interval_or_metric_errors() -> None:
    from agent.refinement_fidelity import validate_explicit_fidelity
    candidate = build_template("pallets", "media", "fixture-color-v1")[0]
    context = RefinementContext(candidates=[candidate], selected_candidate_index=0, current_goal="Count pallets",
        conversation=[], classes=["pallet"], saved_zone_ids=[], clarification_count=0)
    with pytest.raises(ValueError, match="frames per second"):
        validate_explicit_fidelity([RefinementPatch(kind="sample_fps", fps=2)], "Check one frame every two seconds", context)
    validate_explicit_fidelity([RefinementPatch(kind="sample_fps", fps=.5)], "Check one frame every two seconds", context)
    prompt = "Use recall to judge success, and require at least ninety percent."
    with pytest.raises(ValueError, match="metric recall"):
        validate_explicit_fidelity([RefinementPatch(kind="eval_target", eval_target=.9)], prompt, context)
    with pytest.raises(ValueError, match="target 0.9"):
        validate_explicit_fidelity([RefinementPatch(kind="eval_target", eval_target=.5, eval_metric="recall")], prompt, context)
    validate_explicit_fidelity([RefinementPatch(kind="eval_target", eval_target=.9, eval_metric="recall")], prompt, context)
    validate_explicit_fidelity([RefinementPatch(kind="eval_target", eval_target=.8, eval_metric="precision")], "Use recall, no, use precision target .8 instead", context)


@pytest.mark.parametrize("prompt,patch", [
    ("Add a check that the text contains LOT-77.", RefinementPatch(kind="expected_text", expected_text="LOT-77", match_mode="exact")),
    ("The expected label is now SKU-042, and it must match exactly.", RefinementPatch(kind="expected_text", expected_text="SKU-042", match_mode="contains")),
    ("Check that it contains 'Part forty two'.", RefinementPatch(kind="expected_text", expected_text="Part 42", match_mode="contains")),
    ("The expected label is now SKU-042", RefinementPatch(kind="expected_text", expected_text="SKU-001")),
])
def test_explicit_text_literal_and_operator_must_be_preserved(prompt: str, patch: RefinementPatch) -> None:
    from agent.refinement_fidelity import validate_explicit_fidelity
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    context = RefinementContext(candidates=[candidate], selected_candidate_index=0, current_goal="Read labels",
        conversation=[], classes=[], saved_zone_ids=[], clarification_count=0)
    with pytest.raises(ValueError):
        validate_explicit_fidelity([patch], prompt, context)
    validate_explicit_fidelity([RefinementPatch(kind="expected_text", expected_text="LOT-77", match_mode="contains")],
        "Add a check that the text contains LOT-77.", context)
    validate_explicit_fidelity([RefinementPatch(kind="expected_text", expected_text="Part forty two", match_mode="contains")],
        "Check that it contains 'Part forty two'.", context)


def test_text_guard_preserves_reader_defaults_and_literal_operator_words() -> None:
    from agent.refinement_fidelity import validate_explicit_fidelity
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    next(block for block in candidate.blocks if block.type == "match").params.pop("mode", None)
    context = RefinementContext(candidates=[candidate], selected_candidate_index=0, current_goal="Read labels",
        conversation=[], classes=[], saved_zone_ids=[], clarification_count=0)
    for prompt, value in [("Text contains LOT-77", "LOT-77"), ("Text contains 'EXACT'", "EXACT"),
                          ("The expected label is now LOT-EXACT", "LOT-EXACT")]:
        validate_explicit_fidelity([RefinementPatch(kind="expected_text", expected_text=value)], prompt, context)
