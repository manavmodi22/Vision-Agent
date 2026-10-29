"""Capability/selection contracts; synthetic execution is not LLM/model quality."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from agent.executor import execute_candidates
from agent.initial_output import ModelCustomPlanDecision
from agent.machine import AgentConflict, AgentState
from agent.mcp_client import connect_tools
from agent.model_selection import validate_model_choices
from engine.agent_state import AgentStateStore
from engine.builds.manager import BuildManager
from engine.platform.planning_options import (
    options_digest,
    planning_options,
    validate_current_options,
)
from engine.service import WorkspaceService
from spec.planning import BlockedModelOption, PlanningModelOption, PlanningOptions


def option(identifier: str, *, classes: list[str] | None = None, reading: bool = False, synthetic: bool = False) -> PlanningModelOption:
    return PlanningModelOption(capability_id="model." + identifier, model_id=identifier,
        adapter_id="apple-vision" if reading else "fixture-color-v1" if synthetic else "rtdetr-v2-r18",
        task_types=["ocr", "barcode"] if reading else ["detection"], output_contract="texts/v1" if reading else "detections/v1",
        vocabulary="not_applicable" if reading else "open" if classes is None else "closed",
        supported_classes=classes or [], synthetic=synthetic, readiness="unchecked")


def options() -> PlanningOptions:
    value = PlanningOptions(snapshot_id="", project_id="selection-fixture", fixture_source=False,
        eligible_models=[option("owlv2-base-patch16"), option("rtdetr-v2-r18", classes=["person", "pallet"]),
                         option("local-damage", classes=["damaged carton", "damaged pallet"]), option("apple-vision", reading=True)],
        blocked_options=[BlockedModelOption(capability_id="model.uninstalled", reason="Weights unavailable")])
    value.snapshot_id = options_digest(value)
    return value


def choice(identifier: str, classes: list[str] | None = None, **changes: object) -> PatternChoice:
    return PatternChoice.model_validate({"use_case": "custom", "objects": classes or ["person"],
        "metric": "recall", "target": .9, "model_capability_id": "model." + identifier,
        "model_reason": "Proposed compatible adapter; no measured quality claim", **changes})


def test_two_candidate_models_are_resolved_independently_from_saved_options() -> None:
    decision = PlanDecision(message="Compare eligible models", choices=[choice("owlv2-base-patch16"), choice("rtdetr-v2-r18")])
    result = compile_decision(decision, "media", "irrelevant-host-default", options())
    assert [next(block.params["model"] for block in candidate.blocks if block.type == "detect")
            for candidate in result.candidates] == ["owlv2-base-patch16", "rtdetr-v2-r18"]
    assert result.candidates[0].eval == result.candidates[1].eval


@pytest.mark.parametrize("candidate,reason", [
    (choice("invented"), "Unknown"), (choice("uninstalled"), "unavailable"),
    (choice("rtdetr-v2-r18", ["person", "forklift"]), "forklift"),
    (choice("rtdetr-v2-r18", ["people"]), "people"),
    (choice("local-damage", ["carton"]), "carton"),
    (choice("apple-vision"), "does not implement"),
    (choice("owlv2-base-patch16", pipeline_type="ocr", metric="text_accuracy"), "does not implement"),
])
def test_invalid_model_selection_is_rejected_without_compilation(candidate: PatternChoice, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        compile_decision(PlanDecision(message="Invalid proposal", choices=[candidate]), "media", "fixture-color-v1", options())


def test_matching_local_checkpoint_is_eligible_but_not_promoted() -> None:
    decision = PlanDecision(message="Experiment", choices=[choice("local-damage", ["damaged carton", "damaged pallet"])])
    selections = validate_model_choices(decision, options())
    assert selections[0].status == "proposed" and selections[0].model_id == "local-damage"


def test_reading_selection_preserves_exact_and_mismatched_semantics() -> None:
    decision = PlanDecision(message="Read codes", choices=[choice("apple-vision", pipeline_type="barcode", objects=[],
        metric="text_accuracy", expected_text="001-ABC", match_mode="exact", match_emit="mismatched")])
    result = compile_decision(decision, "media", "fixture-color-v1", options())
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", "barcode", "match", "sink_event"]
    assert next(block.params for block in result.candidates[0].blocks if block.type == "match") == {
        "expected": "001-ABC", "mode": "exact", "emit": "mismatched"}


def test_fixture_model_cannot_be_selected_for_real_source_even_if_mislisted() -> None:
    catalog = options()
    catalog.eligible_models.append(option("fixture-color-v1", classes=["pallet"], synthetic=True))
    with pytest.raises(ValueError, match="real project"):
        validate_model_choices(PlanDecision(message="Invalid fixture selection", choices=[choice("fixture-color-v1", ["pallet"])]), catalog)


@pytest.mark.parametrize("change", [{"objects": ["pallet"]}, {"target": .8}, {"count_threshold": 2}, {"metric": "precision"}])
def test_alternatives_must_share_the_same_business_objective(change: dict[str, object]) -> None:
    different = choice("rtdetr-v2-r18").model_copy(update=change)
    with pytest.raises(ValueError, match="same task"):
        validate_model_choices(PlanDecision(message="Incomparable alternatives", choices=[choice("owlv2-base-patch16"), different]), options())


def test_new_model_output_requires_selection_but_legacy_choices_still_load() -> None:
    legacy = {"use_case": "custom", "objects": ["pallet"], "metric": "count_mae", "target": .5,
              "match_mode": "contains", "match_emit": "all"}
    assert PatternChoice.model_validate(legacy).model_capability_id is None
    with pytest.raises(ValidationError) as failed:
        ModelCustomPlanDecision.model_validate({"message": "Count", "questions": [], "choices": [legacy]})
    assert {error["loc"][-1] for error in failed.value.errors()} == {"model_capability_id", "model_reason"}
    with pytest.raises(ValueError, match="captured"):
        compile_decision(PlanDecision(message="No snapshot", choices=[choice("owlv2-base-patch16")]), "media", "fixture-color-v1")


def test_real_catalog_projection_excludes_fixture_on_real_projects_and_is_stable(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Imported-media app", "custom")
    first = planning_options(service, project.id)
    assert first == planning_options(service, project.id) and first.snapshot_id == options_digest(first)
    assert "model.fixture-color-v1" not in {item.capability_id for item in first.eligible_models}
    assert any(item.capability_id == "model.fixture-color-v1" for item in first.blocked_options)
    with pytest.raises(ValueError, match="synthetic"):
        planning_options(service, project.id, "fixture-color-v1")
    assert "detector_model" not in BuildManager(service).settings(project.id)


def test_explicit_fixture_constraint_preserves_vocabulary_and_reading_options(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Synthetic benchmark", "custom")
    service.demo(project.id)
    catalog = planning_options(service, project.id, "fixture-color-v1")
    detectors = [item for item in catalog.eligible_models if "detection" in item.task_types]
    assert [item.model_id for item in detectors] == ["fixture-color-v1"]
    assert detectors[0].vocabulary == "closed" and "pallet" in detectors[0].supported_classes
    with pytest.raises(ValueError, match="forklift"):
        validate_model_choices(PlanDecision(message="Wrong fixture class", choices=[choice("fixture-color-v1", ["forklift"])]), catalog)


def test_failed_catalog_smoke_is_not_reclassified_as_unchecked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.platform.planning_options as module

    service = WorkspaceService(tmp_path)
    project = service.create_project("Blocked installed adapter", "custom")
    service.demo(project.id)
    fixture = next(item for item in module.model_catalog() if item.id == "model.fixture-color-v1")
    fixture.callable = False
    fixture.readiness.state = "blocked"
    fixture.readiness.reason = "Synthetic self-test failed"
    monkeypatch.setattr(module, "model_catalog", lambda: [fixture])
    catalog = planning_options(service, project.id, "fixture-color-v1")
    assert not catalog.eligible_models
    assert catalog.blocked_options[0].reason == "Synthetic self-test failed"


def test_selected_metadata_change_is_rejected_and_unrelated_options_do_not_retarget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.platform.planning_options as module
    service = WorkspaceService(tmp_path)
    project = service.create_project("Catalog binding", "custom")
    service.demo(project.id)
    saved = planning_options(service, project.id, "fixture-color-v1")
    current = saved.model_copy(deep=True)
    current.eligible_models[0].version = "changed-adapter"
    monkeypatch.setattr(module, "_project_options", lambda *args: current)
    with pytest.raises(ValueError, match="changed"):
        validate_current_options(service, saved, [current.eligible_models[0].capability_id])
    unrelated = saved.model_copy(deep=True)
    unrelated.blocked_options.append(BlockedModelOption(capability_id="model.future", reason="not installed"))
    monkeypatch.setattr(module, "_project_options", lambda *args: unrelated)
    validate_current_options(service, saved, ["model.fixture-color-v1"])


async def test_actual_mcp_binds_options_before_fixture_execution_and_replays_without_model_default(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Per-model MCP fixture", "custom")
    service.demo(project.id)
    state = AgentStateStore(service)
    async with connect_tools(str(tmp_path), AgentState()) as tools:
        # Legacy host model differs deliberately; execution must use the saved selection.
        await tools.start_run(project.id, "Count pallets", "media", "owlv2-base-patch16")
        raw = await tools.call("planning_options", {"project_id": project.id, "detection_constraint": "fixture-color-v1", "operation_id": tools.operation_id})
        catalog = PlanningOptions.model_validate(raw)
        await tools.control("agent_record_options", {"snapshot_id": catalog.snapshot_id})
        decision = PlanDecision(message="Synthetic transport test, not LLM quality", choices=[
            choice("fixture-color-v1", ["pallet"], metric="count_mae", target=.5)])
        await tools.control("agent_record_decision", {"decision": decision.model_dump(mode="json")})
        result = compile_decision(decision, "media", "owlv2-base-patch16", catalog)
        await execute_candidates(tools, result, "media", "owlv2-base-patch16")
        result.operation_id, result.tool_calls = tools.operation_id, tools.state.budget.tool_calls
        await tools.control("agent_stage_plan", {"result": result.model_dump(mode="json", by_alias=True)})
    state.commit_plan(project.id, result.operation_id, result, "Count pallets")
    plan = state.platform.plans(project.id)[0]
    assert plan.planning_options_artifact_id and plan.model_selections[0].model_id == "fixture-color-v1"
    assert state.platform.artifact_content(project.id, plan.planning_options_artifact_id).content == catalog.model_dump(mode="json")
    execution = state.platform.execution(project.id, result.operation_id)
    assert execution
    assert plan.planning_options_artifact_id in {artifact.id for artifact in state.platform.replay(project.id, execution.id).artifacts}
    replay = state.replay(project.id, result.operation_id)
    assert replay.reproduced and not replay.effects_executed
    operation = state.operation(project.id, result.operation_id)
    assert operation.calls[0].name == "planning_options" and operation.planning_options == catalog
    assert not service.events(project.id)


def test_options_receipt_cannot_be_invented_or_attached_after_decision(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Receipt checks", "custom")
    service.demo(project.id)
    state = AgentStateStore(service)
    operation = state.begin(project.id, "Count pallets", "media", "fixture-color-v1")
    with pytest.raises(AgentConflict, match="captured"):
        state.record_options(project.id, operation.id, "0" * 64)
    with pytest.raises(AgentConflict, match="captured"):
        state.record_decision(project.id, operation.id, PlanDecision(message="No capability receipt", choices=[choice("fixture-color-v1", ["pallet"])]))
    state.record_decision(project.id, operation.id, PlanDecision(message="Legacy fixture", choices=[PatternChoice(
        use_case="custom", objects=["pallet"], metric="count_mae", target=.5)]))
    with pytest.raises(AgentConflict, match="before"):
        state.record_options(project.id, operation.id, "0" * 64)


def test_reading_plan_has_only_relevant_experiments_and_conditional_checkpoints() -> None:
    from agent.machine import Phase
    from agent.templates import build_template
    from engine.platform.experiments import experiment_policy
    reading = build_template("labels", "media", "unused")[0]
    experiments, checkpoints = experiment_policy([reading], Phase.COMPILE)
    assert [experiment.phase for experiment in experiments] == ["compile", "evaluate"]
    assert all("train" not in tool for experiment in experiments for tool in experiment.allowed_tools)
    assert {checkpoint.id for checkpoint in checkpoints} == {"labels", "deployment"}
    assert "Only if" in next(checkpoint.description for checkpoint in checkpoints if checkpoint.id == "deployment")
    with pytest.raises(ValueError, match="reading-only"):
        experiment_policy([reading], Phase.SPECIALIZE)


def test_options_cannot_be_attributed_after_a_model_request(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Pre-call provenance", "custom")
    service.demo(project.id)
    state = AgentStateStore(service)
    operation = state.begin(project.id, "Count pallets", "media", "fixture-color-v1")
    call = state.start_call(project.id, operation.id, "llm", "explicit-fake-model", {})
    state.finish_call(project.id, operation.id, call.id, {"test": True})
    with pytest.raises(AgentConflict, match="before the first model"):
        state.record_options(project.id, operation.id, "0" * 64)
    assert not state.platform.plans(project.id)


def test_selected_catalog_change_stops_publication_before_compile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.platform.planning_options as module

    service = WorkspaceService(tmp_path)
    project = service.create_project("Selected adapter changed", "custom")
    service.demo(project.id)
    state = AgentStateStore(service)
    operation = state.begin(project.id, "Count pallets", "media", "fixture-color-v1")
    saved = planning_options(service, project.id, "fixture-color-v1", request="Count pallets")
    call = state.start_call(project.id, operation.id, "tool", "planning_options", {"project_id": project.id})
    state.finish_call(project.id, operation.id, call.id, saved.model_dump(mode="json"))
    state.record_options(project.id, operation.id, saved.snapshot_id)
    state.record_decision(project.id, operation.id, PlanDecision(message="Synthetic candidate", choices=[
        choice("fixture-color-v1", ["pallet"], metric="count_mae", target=.5)]))
    changed = saved.model_copy(deep=True)
    next(item for item in changed.eligible_models if item.model_id == "fixture-color-v1").version = "replacement"
    monkeypatch.setattr(module, "_project_options", lambda *args: changed)
    before = service.get_project(project.id), service.annotations(project.id)
    with pytest.raises(ValueError, match="changed"):
        state.prepare_compile(project.id, operation.id, 1)
    assert not state.platform.plans(project.id)
    assert before == (service.get_project(project.id), service.annotations(project.id))


def test_detector_training_experiment_exists_only_in_approved_specialization_phase() -> None:
    from agent.machine import TOOLS, Phase
    from agent.templates import build_template
    from engine.platform.experiments import experiment_policy
    detector = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    normal, checkpoints = experiment_policy([detector], Phase.COMPILE)
    assert "specialize" not in {experiment.phase for experiment in normal}
    assert "training" not in {checkpoint.id for checkpoint in checkpoints}
    training, _ = experiment_policy([detector], Phase.SPECIALIZE)
    assert [experiment.phase for experiment in training] == ["specialize"]
    assert "build_train" in training[0].allowed_tools
    assert set(training[0].allowed_tools) <= TOOLS[Phase.SPECIALIZE]


def test_previous_schema_plan_hash_remains_readable_but_tampering_is_rejected(tmp_path: Path) -> None:
    import json

    from agent.machine import Phase
    from agent.templates import build_template
    from engine.platform.store import PlatformStore, digest

    service = WorkspaceService(tmp_path)
    project = service.create_project("Legacy saved plan", "custom")
    service.demo(project.id)
    platform = PlatformStore(service)
    candidate = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    plan, _ = platform.publish(project.id, "a" * 32, "Count pallets", [candidate], Phase.COMPILE, "legacy fixture")
    additive = {"planning_options_artifact_id", "model_selections"}
    canonical = plan.model_dump(mode="json", by_alias=True, exclude={"content_hash", *additive})
    stored = plan.model_dump(mode="json", exclude=additive)
    stored["content_hash"] = digest(canonical)
    path = platform.path(project.id, "plans", plan.id)
    path.write_text(json.dumps(stored))
    restored = platform.plan(project.id, plan.id)
    assert restored.model_selections == [] and restored.planning_options_artifact_id is None
    assert restored.candidates == [candidate]
    stored["goal"] = "Tampered request"
    path.write_text(json.dumps(stored))
    with pytest.raises(AgentConflict, match="hash"):
        platform.plan(project.id, plan.id)


def test_invalid_reading_training_revision_does_not_supersede_executable_plan(tmp_path: Path) -> None:
    from agent.machine import Phase
    from agent.templates import build_template
    from engine.platform.store import PlatformStore

    service = WorkspaceService(tmp_path)
    project = service.create_project("Read text", "custom")
    platform = PlatformStore(service)
    candidate = build_template("labels", "media", "unused")[0]
    plan, run = platform.publish(project.id, "b" * 32, "Read labels", [candidate], Phase.COMPILE, "initial")
    with pytest.raises(ValueError, match="reading-only"):
        platform.publish(project.id, "b" * 32, "Read labels", [candidate], Phase.SPECIALIZE, "invalid training")
    assert platform.execution(project.id, run.operation_id) == run
    assert platform.plans(project.id) == [plan]
