"""Known delivery capability checks; fixture inference is not model-quality evidence."""

from pathlib import Path

import pytest

from agent.machine import AgentConflict, AgentState
from agent.mcp_client import connect_tools
from agent.refinement import interpret_refinement
from agent.refinement_capabilities import CAPABILITY_QUESTION, delivery_question
from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
from agent.templates import build_template
from engine.builds.manager import BuildManager
from engine.builds.store import BuildStore
from engine.service import WorkspaceService
from spec.build import BuildContinueRequest
from spec.models import PipelineSpec
from spec.refinement import RefinementBatch, RefinementContext, RefinementPatch

COMPOUND = "Raise confidence to 0.6 and send an email whenever a pallet is detected."


@pytest.mark.parametrize("prompt", [
    COMPOUND, "Publish every detection to MQTT.", "Configure a webhook for alerts.",
    "Send me an email when count exceeds 5.", "Email me whenever a pallet is detected.",
    "Set up email notifications and lower confidence to .2.", "Add an MQTT destination.",
    "Don't send email, but publish notifications to MQTT.",
    "Send an 'email' when the count exceeds 5.",
])
def test_explicit_delivery_actions_require_separate_setup(prompt: str) -> None:
    assert delivery_question(prompt) == CAPABILITY_QUESTION


@pytest.mark.parametrize("prompt", [
    "Also detect email icons.", 'Add "email icon" as an object class.', "Add email as a class.",
    "Detect MQTT sensors and webhook logos.", 'Read labels containing "send an email".',
    'Read labels containing "email me".',
    'Read labels containing "send an email and publish MQTT".',
    "Raise confidence to .6 and don't send an email.",
    "Create a local event at 5 pallets without email or MQTT notifications.",
    "Do not send email or publish MQTT notifications; set confidence to .6.",
    COMPOUND + "\nUser clarification: Only change confidence to 0.6; skip email.",
    COMPOUND + "\nUser clarification: Apply confidence 0.6 without delivery setup.",
])
def test_classes_literals_negations_and_explicit_withdrawal_are_preserved(prompt: str) -> None:
    assert delivery_question(prompt) is None


def test_switching_channel_does_not_authorize_partial_edits() -> None:
    assert delivery_question(COMPOUND + "\nUser clarification: Skip email, publish to MQTT instead.")


def test_yes_requires_the_actual_vision_only_question() -> None:
    prompt = COMPOUND + "\nUser clarification: Yes, please."
    assert delivery_question(prompt, CAPABILITY_QUESTION) is None
    assert delivery_question(prompt, "Should I send email?") == CAPABILITY_QUESTION
    assert delivery_question(COMPOUND + "\nUser clarification: Yes, also publish to MQTT.", CAPABILITY_QUESTION)


def fixture_app(root: Path) -> tuple[WorkspaceService, str, PipelineSpec]:
    service = WorkspaceService(root)
    project = service.create_project("Capability guard fixture", "custom")
    service.demo(project.id)
    spec = build_template("pallets", "media", "fixture-color-v1")[0]
    service.save_candidates(project.id, [spec], "Count pallets by lane")
    service.evaluate(project.id, 0)
    service.deploy(project.id, 0, approved=True, override_reason="Isolated synthetic capability guard test", approval_scope="local_trial")
    return service, project.id, spec


def evidence(service: WorkspaceService, project_id: str) -> dict[str, object]:
    root = service.root(project_id)
    project = service.get_project(project_id)
    return {"candidates": project.candidates, "labels": service.annotations(project_id),
            "evaluations": project.evaluations, "deployment_id": project.deployment_id,
            "deployment": (root / "deployment.json").read_bytes(),
            "ontology": (root / "dataset-metadata.json").read_bytes() if (root / "dataset-metadata.json").exists() else None,
            "eval_media": (root / "eval-media.json").read_bytes(), "events": service.events(project_id)}


async def test_capability_preflight_is_recorded_without_model_call_or_mutation(tmp_path: Path) -> None:
    service, project_id, _ = fixture_app(tmp_path)
    before = evidence(service, project_id)
    store = BuildStore(service)
    record = store.create(project_id, COMPOUND)
    decision = await interpret_refinement(COMPOUND, {"project_id": project_id, "mcp_data_dir": str(tmp_path),
        "model_url": "http://127.0.0.1:1/v1", "planner_model": "intentionally-absent"}, record.view.id)
    assert decision.source == "capability_guard" and decision.questions == [CAPABILITY_QUESTION] and not decision.patches
    saved = store.get(project_id)
    assert saved.refinement_decisions == [decision.model_dump(mode="json")]
    assert [call.name for call in saved.operation.calls] == ["build_refinement_context"]
    assert saved.operation.state.budget.model_calls == 0
    assert evidence(service, project_id) == before


@pytest.mark.parametrize("legacy_batch", [False, True])
async def test_real_mcp_rejects_delivery_before_patch_even_with_legacy_captured_decision(tmp_path: Path, legacy_batch: bool) -> None:
    service, project_id, _ = fixture_app(tmp_path)
    before = evidence(service, project_id)
    store = BuildStore(service)
    record = store.create(project_id, COMPOUND)
    patches = [RefinementPatch(kind="confidence", confidence=.6),
               RefinementPatch(kind="add_classes", classes=["email"]),
               RefinementPatch(kind="count_rule", count_threshold=1)]
    # Replay an old, already accepted bad decision to prove the server barrier is
    # independent of the new interpreter preflight and capture-time validation.
    record.refinement_decisions = [{"message": "Unsafe historical interpretation", "questions": [],
                                   "patches": [patch.model_dump(mode="json") for patch in patches]}]
    store.save(record)
    payload = {"batch": RefinementBatch(patches=patches).model_dump(mode="json")} if legacy_batch else {"patch": patches[0].model_dump(mode="json")}
    with pytest.raises(ExceptionGroup, match="TaskGroup") as failed:
        async with connect_tools(str(tmp_path), AgentState()) as tools:
            await tools.bind_build(project_id, record.view.id)
            await tools.call("build_refine", {"project_id": project_id, "build_id": record.view.id, **payload})
    assert "Delivery setup" in str(failed.value.exceptions)
    assert evidence(service, project_id) == before
    call = store.get(project_id).operation.calls[-1]
    assert call.name == "build_refine" and call.status == "failed" and "Delivery setup" in (call.error or "")


def test_recording_and_intent_validation_cannot_accept_partial_bad_model_patch(tmp_path: Path) -> None:
    service, project_id, spec = fixture_app(tmp_path)
    store = BuildStore(service)
    record = store.create(project_id, COMPOUND)
    decision = RefinementDecision(message="Confidence changed", questions=[], patches=[RefinementPatch(kind="confidence", confidence=.6)])
    context = RefinementContext(candidates=[spec], selected_candidate_index=0, current_goal="Count pallets", conversation=[],
                                classes=["pallet"], saved_zone_ids=[], clarification_count=0)
    with pytest.raises(ValueError, match="Delivery setup"):
        validate_refinement_intent(decision, COMPOUND, context)
    with pytest.raises(AgentConflict, match="Delivery setup"):
        store.record_refinement_decision(project_id, record.view.id, decision.model_dump(mode="json"))
    with pytest.raises(AgentConflict, match="actual user request"):
        store.record_refinement_decision(project_id, record.view.id, RefinementDecision(
            source="capability_guard", message="invented", questions=["invented"], patches=[]).model_dump(mode="json"))


async def test_manager_pauses_unchanged_then_explicit_vision_only_answer_can_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import agent.refinement as module
    service, project_id, original = fixture_app(tmp_path)
    before = evidence(service, project_id)
    manager = BuildManager(service)
    try:
        await manager.start(project_id, COMPOUND)
        await manager.tasks[project_id]
        status = manager.status(project_id)
        assert status.status == "awaiting_clarification" and "Alerts" in status.message
        assert evidence(service, project_id) == before
        assert not any(call.kind == "llm" for call in manager.store.get(project_id).operation.calls)
        # Only interpretation is a named deterministic test double. The later
        # patch, compiler, actual fixture previews, and evaluation still use MCP.
        async def check_model(url: str, model: str) -> None:
            pass
        async def interpret(prompt: str, context: object, tools: object, url: str, model: str) -> RefinementDecision:
            assert prompt.endswith("Only change confidence to 0.6; skip email.")
            decision = RefinementDecision(message="Set confidence to 0.6", questions=[], patches=[RefinementPatch(kind="confidence", confidence=.6)])
            record = manager.store.get(project_id)
            call = manager.store.start_model_call(project_id, record.view.id, "deterministic-capability-resume-test", {})
            manager.store.finish_call(project_id, record.view.id, call.id, {"decision": decision.model_dump(mode="json")})
            return decision
        monkeypatch.setattr(module, "check_model", check_model)
        monkeypatch.setattr(module, "_interpret_local", interpret)
        await manager.continue_build(project_id, BuildContinueRequest(prompt="Only change confidence to 0.6; skip email."))
        await manager.tasks[project_id]
        status = manager.status(project_id)
        assert status.status in {"awaiting_review", "awaiting_improvement"}, status.message
        expected = original.model_copy(deep=True)
        next(block for block in expected.blocks if block.type == "detect").params["min_conf"] = .6
        assert service.candidate(project_id, 0) == expected
        assert service.annotations(project_id) == before["labels"]
        assert not (service.root(project_id) / "deployment.json").exists()
        assert not service.events(project_id)
    finally:
        await manager.close()
