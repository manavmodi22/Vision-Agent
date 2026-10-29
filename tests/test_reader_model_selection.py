"""Reader-choice software contracts; mocked readers establish no OCR accuracy."""
from pathlib import Path
from time import time
from typing import Literal, cast

import pytest
from PIL import Image
from pydantic import ValidationError

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from agent.executor import execute_candidates
from agent.machine import AgentConflict, AgentError, AgentState, Phase
from agent.mcp_client import MCPTools
from agent.model_selection import validate_model_choices
from agent.replay import replay_operation
from agent.state_contracts import AgentOperation, CapturedCall
from engine.adapters.contracts import BarcodeRequest, OcrRequest
from engine.adapters.requests import request_for_block
from engine.blocks.params import ReadingParams
from engine.blocks.reading import VisionReading
from engine.builds.refinement_edits import apply_edit
from engine.compiler import compile_pipeline
from engine.eval.hashes import spec_hash
from engine.eval.protocol import freeze_protocol
from engine.eval.recipe import task_signature
from engine.platform.planning_options import options_digest, planning_options
from engine.runtime.executor import execute_frame
from engine.runtime.values import ExecutionState
from engine.service import WorkspaceService
from spec.planning import PlanningModelOption, PlanningOptions
from spec.refinement import RefinementPatch

Version = Literal["0.1", "0.2", "0.3"]
PADDLE = "ppocr-v5-mobile-en"


def options(version: Version = "0.3") -> PlanningOptions:
    models = ["apple-vision", PADDLE] if version == "0.3" else ["apple-vision"]
    result = PlanningOptions(schema_version=version, snapshot_id="", project_id="software-contract",
        fixture_source=False, blocked_options=[], eligible_models=[PlanningModelOption(
            capability_id="model." + model, model_id=model,
            adapter_id="apple-vision" if model == "apple-vision" else "paddle-ocr-cpu",
            task_types=["ocr", "barcode"] if model == "apple-vision" else ["ocr"],
            output_contract="texts/v1", vocabulary="not_applicable", readiness="unchecked",
            selection_basis="legacy" if version == "0.1" else "default") for model in models])
    result.snapshot_id = options_digest(result)
    return result


def decision(model: str = "apple-vision", task: Literal["ocr", "barcode"] = "ocr") -> PlanDecision:
    return PlanDecision(message="Explicit software-test proposal", choices=[PatternChoice(
        use_case="custom", pipeline_type=task, objects=[], metric="text_accuracy", target=.95,
        model_capability_id="model." + model, model_reason="Proposed reader experiment; no quality claim")])


@pytest.fixture
def bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mock-native-bridge"
    path.write_bytes(b"test-bridge-v1")
    monkeypatch.setenv("VISION_APP_BINARY", str(path))
    return path


def test_legacy_reader_defaults_and_barcode_contract_are_separate() -> None:
    assert ReadingParams().model == OcrRequest().model_id == BarcodeRequest().model_id == "apple-vision"
    with pytest.raises(ValidationError):
        ReadingParams(model="invented-reader")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        BarcodeRequest(model_id=PADDLE)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="en-US"):
        OcrRequest(model_id=PADDLE, languages=["fr-FR"])


def test_new_candidates_bind_each_reader_without_changing_task_or_target() -> None:
    proposal = decision()
    proposal.choices.extend(decision(PADDLE).choices)
    result = compile_decision(proposal, "media", "irrelevant-detector", options())
    assert [candidate.blocks[-1].params for candidate in result.candidates] == [
        {"model": "apple-vision"}, {"model": PADDLE}]
    assert [request_for_block(candidate.blocks[-1]).model_id for candidate in result.candidates] == ["apple-vision", PADDLE]  # type: ignore[union-attr]
    assert result.candidates[0].eval == result.candidates[1].eval
    assert [selection.model_id for selection in validate_model_choices(proposal, options())] == ["apple-vision", PADDLE]
    assert all(block.type not in {"rule", "match", "sink_event"} for candidate in result.candidates for block in candidate.blocks)
    with pytest.raises(ValueError, match="does not implement task barcode"):
        compile_decision(decision(PADDLE, "barcode"), "media", "ignored", options())


@pytest.mark.parametrize("version", ["0.1", "0.2", "0.3"])
def test_versioned_apple_graph_and_captured_replay_are_unchanged(version: Version) -> None:
    catalog, proposal = options(version), decision()
    result = compile_decision(proposal, "media", "old-host-detector", catalog)
    assert result.candidates[0].blocks[-1].params == ({"model": "apple-vision"} if version == "0.3" else {})
    state = AgentState()
    state.budget.tool_calls = 2
    result.operation_id, result.tool_calls = "legacy-op", 2
    spec = result.candidates[0].model_dump(mode="json", by_alias=True)
    operation = AgentOperation(id="legacy-op", project_id="legacy", trace_id="trace", root_span_id="span",
        owner_pid=1, deadline=time() + 30, status="completed", input_fingerprint="captured",
        brief="Read label text", source_path="media", detector_model="old-host-detector", state=state,
        planning_options=catalog, decision=proposal, result=result, calls=[
            CapturedCall(id="validate", kind="tool", name="pipeline_validate", started_ns=1, ended_ns=2,
                status="completed", request={"spec": spec}, result={"valid": True}),
            CapturedCall(id="preview", kind="tool", name="pipeline_run", started_ns=3, ended_ns=4,
                status="completed", request={"spec": spec}, result={"frames": [{"software_fixture": True}]})])
    replay = replay_operation(operation)
    assert replay.reproduced and not replay.effects_executed
    assert replay.result == result


def test_explicit_apple_compiles_and_executes_through_common_boundary(
    bridge: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.adapters.legacy as legacy
    monkeypatch.setattr(legacy, "read_native", lambda image: VisionReading(texts=["ABC-001"]))
    candidate = compile_decision(decision(), "media", "ignored", options()).candidates[0]
    image = tmp_path / "example.png"
    Image.new("RGB", (80, 30), "white").save(image)
    compiled = compile_pipeline(candidate, tmp_path)
    assert compiled.inference_identities["read"].model_id == "apple-vision"
    result = execute_frame(compiled, image, 0, ExecutionState())
    assert result.texts == ["ABC-001"]
    assert result.inferences[0].result.identity == compiled.inference_identities["read"]
    before = spec_hash(candidate, tmp_path)
    bridge.write_bytes(b"test-bridge-v2")
    assert before != spec_hash(candidate, tmp_path)
    with pytest.raises(ValueError, match="identity changed"):
        execute_frame(compiled, image, 0, ExecutionState())


def test_unimplemented_reader_never_falls_back_to_native(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.adapters.identity as identity
    import engine.adapters.legacy as legacy
    real_adapter = identity.adapter_id
    def absent(model: str) -> str:
        if model == PADDLE:
            raise ValueError("No implemented adapter for the requested test reader")
        return real_adapter(model)
    monkeypatch.setattr(identity, "adapter_id", absent)
    monkeypatch.setattr(legacy, "read_native", lambda image: pytest.fail("A missing reader must not invoke Apple"))
    with pytest.raises(ValueError, match="reader|adapter"):
        legacy.execute_legacy(Image.new("RGB", (8, 8)), OcrRequest(model_id=PADDLE))
    from engine.adapters.registry import run_inference
    with pytest.raises(ValueError, match="No implemented adapter"):
        run_inference(Image.new("RGB", (8, 8)), OcrRequest(model_id=PADDLE))
    candidate = compile_decision(decision(PADDLE), "media", "ignored", options()).candidates[0]
    with pytest.raises(ValueError, match="No implemented adapter"):
        compile_pipeline(candidate, tmp_path)


def test_catalog_metadata_cannot_create_a_reader_implementation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.platform.planning_options as module
    service = WorkspaceService(tmp_path)
    project = service.create_project("Reader capability software test", "custom")
    fake = next(item for item in module.model_catalog() if item.id == "model.fixture-color-v1")
    fake.id, fake.task_types = "model." + PADDLE, ["ocr"]
    monkeypatch.setattr(module, "model_catalog", lambda: [fake])
    monkeypatch.setattr(module, "adapter_id", lambda _: (_ for _ in ()).throw(ValueError("No implemented reader")))
    result = planning_options(service, project.id)
    assert result.schema_version == "0.3" and not result.eligible_models
    assert result.blocked_options[0].reason == "No implemented reader"


def test_available_reader_projection_uses_tasks_and_coded_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.platform.planning_options as module
    service = WorkspaceService(tmp_path)
    project = service.create_project("Future-reader contract only", "custom")
    service.demo(project.id)
    fake = next(item for item in module.model_catalog() if item.id == "model.fixture-color-v1")
    fake.id, fake.task_types, fake.callable = "model." + PADDLE, ["ocr"], False
    fake.readiness.state = "unchecked"
    monkeypatch.setattr(module, "model_catalog", lambda: [fake])
    monkeypatch.setattr(module, "adapter_id", lambda _: "paddle-ocr-cpu")
    result = planning_options(service, project.id, "fixture-color-v1")
    assert len(result.eligible_models) == 1
    reader = result.eligible_models[0]
    assert reader.task_types == ["ocr"] and reader.output_contract == "texts/v1"
    assert reader.vocabulary == "not_applicable" and reader.readiness == "unchecked"


@pytest.mark.parametrize("version", ["0.2", "0.3"])
def test_current_options_still_bind_the_originating_user_request(tmp_path: Path, version: Version) -> None:
    from engine.agent_state import AgentStateStore
    service = WorkspaceService(tmp_path)
    project = service.create_project("Request authorization fixture", "custom")
    service.demo(project.id)
    store = AgentStateStore(service)
    operation = store.begin(project.id, "Count pallets", "media", "fixture-color-v1")
    forged = planning_options(service, project.id, request="Use another explicitly named model")
    forged.schema_version = version
    forged.snapshot_id = options_digest(forged)
    call = store.start_call(project.id, operation.id, "tool", "planning_options", {"project_id": project.id})
    store.finish_call(project.id, operation.id, call.id, forged.model_dump(mode="json"))
    with pytest.raises(AgentConflict, match="originating user brief"):
        store.record_options(project.id, operation.id, forged.snapshot_id)
    assert not store.platform.plans(project.id) and not service.events(project.id)


def test_refinements_preserve_distinct_reader_choices() -> None:
    for model in ("apple-vision", PADDLE):
        candidate = compile_decision(decision(model), "media", "ignored", options()).candidates[0]
        original_reader = candidate.blocks[-1].model_copy(deep=True)
        for patch in [RefinementPatch(kind="expected_text", expected_text="NEW-002"),
                      RefinementPatch(kind="sample_fps", fps=1),
                      RefinementPatch(kind="eval_target", eval_target=.99)]:
            apply_edit(candidate, patch, {})
        assert next(block for block in candidate.blocks if block.type == "ocr") == original_reader


def test_ocr_alternatives_share_a_protocol_but_barcode_does_not(
    bridge: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.compiler as compiler
    import engine.eval.hashes as hashes
    from engine.adapters.identity import resolve_execution_identity
    from spec.inference import ExecutionIdentity
    # Simulate only a future installed reader identity; no Paddle inference is claimed.
    def test_identity(request: OcrRequest | BarcodeRequest) -> ExecutionIdentity:
        original = resolve_execution_identity(OcrRequest() if request.model_id == PADDLE else request)
        if request.model_id != PADDLE:
            return original
        return original.model_copy(update={"model_id": PADDLE, "capability_id": "model." + PADDLE,
            "adapter_id": "paddle-ocr-cpu", "identity_hash": "b" * 64})
    monkeypatch.setattr(compiler, "resolve_execution_identity", test_identity)
    monkeypatch.setattr(hashes, "resolve_execution_identity", test_identity)
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Synthetic protocol contract", "custom")
    service.demo(project.id)
    root, dataset = service.root(project.id), service.annotations(project.id)
    candidates = [compile_decision(decision(model), "media", "ignored", options()).candidates[0]
                  for model in ("apple-vision", PADDLE)]
    assert task_signature(candidates[0], root) == task_signature(candidates[1], root)
    protocol = freeze_protocol(root, dataset, candidates, [0, 1], "validation")
    assert len(protocol.candidates) == 2 and protocol.metric == "text_accuracy"
    assert protocol.candidates[0].spec_hash != protocol.candidates[1].spec_hash
    barcode = compile_decision(decision(task="barcode"), "media", "ignored", options()).candidates[0]
    assert task_signature(candidates[0], root) != task_signature(barcode, root)
    with pytest.raises(ValueError, match="share output task"):
        freeze_protocol(root, dataset, [candidates[0], barcode], [0, 1], "validation")


def test_selected_ocr_capability_does_not_require_an_unselected_native_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.capabilities as catalog
    from engine.capabilities.blocks import block_catalog
    service = WorkspaceService(tmp_path)
    fake = next(item for item in catalog.model_catalog() if item.id == "model.fixture-color-v1")
    fake.id, fake.task_types, fake.callable = "model." + PADDLE, ["ocr"], False
    fake.readiness.state = "unchecked"
    monkeypatch.setattr(catalog, "model_catalog", lambda: [fake])
    catalog.validate_experiment_capabilities(service, ["block.ocr", "model." + PADDLE])
    with pytest.raises(ValueError, match="apple-vision"):
        catalog.validate_experiment_capabilities(service, ["block.barcode", "model." + PADDLE])
    block = next(row for row in block_catalog([fake]) if row.id == "block.ocr")
    assert block.installation_ready and not block.callable
    assert "model.apple-vision" not in block.dependencies


async def test_saved_reader_selection_mismatch_stops_before_validation_or_inference(
    bridge: Path, tmp_path: Path,
) -> None:
    from engine.platform.store import PlatformStore
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Saved reader authority fixture", "custom")
    service.demo(project.id)
    captured = options()
    captured.project_id = project.id
    captured.snapshot_id = options_digest(captured)
    proposal = decision()
    result = compile_decision(proposal, "media", "ignored", captured)
    store = PlatformStore(service)
    plan, _ = store.publish(project.id, "a" * 32, "Read text", result.candidates, Phase.COMPILE,
        "Explicit software fixture", planning_options=captured,
        model_selections=validate_model_choices(proposal, captured))
    assert "model.apple-vision" in plan.required_capabilities
    assert "model." + PADDLE not in plan.required_capabilities
    assert store.plan(project.id, plan.id).candidates == result.candidates
    changed = plan.model_copy(deep=True)
    changed.model_selections[0].model_id = PADDLE
    class RecordedTools:
        project_id = project.id
        async def control(self, name: str, arguments: object) -> dict[str, object]:
            return changed.model_dump(mode="json") if name == "agent_plan_read" else {}
        async def call(self, name: str, arguments: object) -> dict[str, object]:
            pytest.fail("A saved model mismatch must stop before any validation/inference tool")
    with pytest.raises(AgentError, match="reader differs"):
        await execute_candidates(cast(MCPTools, RecordedTools()), result, "media", "ignored")
    assert not service.events(project.id) and service.get_project(project.id).deployment_id is None
