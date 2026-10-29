"""Recorded facts and coded selection scope; no learned inference or quality claim."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from agent.machine import AgentConflict, AgentState
from agent.mcp_client import connect_tools
from engine.agent_state import AgentStateStore
from engine.models.local_manifest import LocalDetectorManifest
from engine.platform.model_request import explicit_model_ids
from engine.platform.planning_options import (
    options_digest,
    planning_options,
    validate_current_options,
)
from engine.service import WorkspaceService
from spec.capabilities import CapabilityManifest
from spec.planning import PlanningOptions


def manifest(identifier: str, **changes: object) -> LocalDetectorManifest:
    return LocalDetectorManifest.model_validate(dict(id=identifier, classes=["person"], training_hash="a" * 64,
        evaluation_hash="b" * 64, created_at="2026-10-28", training_samples=1, epochs_completed=1,
        steps=1, final_loss=3.0, **changes))


def capability(identifier: str) -> CapabilityManifest:
    return CapabilityManifest.model_validate(dict(id="model." + identifier, name=identifier,
        kind="model", description="Metadata fixture only; never execute", availability="installed",
        implemented=True, installation_ready=True, callable=False, task_types=["detection"],
        license={"identifier":"MIT"}, provenance={"scope":"registry_metadata"}, hardware={},
        install_method="local_training", readiness={"state":"unchecked", "reason":"test metadata",
            "checked_at":"2026-10-28", "evidence_scope":"prerequisites"}))


@pytest.fixture
def inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[WorkspaceService, str, Path]:
    import engine.platform.planning_options as module

    root = tmp_path / "models"
    monkeypatch.setenv("VISION_MODELS_DIR", str(root))
    records = [manifest("local-unknown"),
        manifest("local-engineering", use_scope="engineering_smoke", use_scope_evidence_ref="test-run:1", initialization="random", training_state="optimization_completed"),
        manifest("local-user-smoke-in-name", use_scope="user_candidate", use_scope_evidence_ref="training-job:2", initialization="random", training_state="optimization_completed"),
        manifest("local-untrained", use_scope="user_candidate", use_scope_evidence_ref="training-job:3", training_state="untrained")]
    for record in records:
        path = root / record.id / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text(record.model_dump_json())
    identifiers = [record.id for record in records] + ["owlv2-base-patch16"]
    monkeypatch.setattr(module, "model_catalog", lambda: [capability(identifier) for identifier in identifiers])
    monkeypatch.setattr(module, "list_models", lambda: [{"id": identifier, "backend": "ssdlite320"} for identifier in identifiers])
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Selection metadata fixture", "custom")
    return service, project.id, root


def test_defaults_preserve_user_candidate_but_explain_unknown_and_engineering(inventory: tuple[WorkspaceService, str, Path]) -> None:
    service, project_id, _ = inventory
    result = planning_options(service, project_id, request="Count people")
    assert {item.model_id for item in result.eligible_models} == {"owlv2-base-patch16", "local-user-smoke-in-name"}
    assert {item.model_id for item in result.experimental_models} == {"local-unknown", "local-engineering", "local-untrained"}
    unknown = next(item for item in result.experimental_models if item.model_id == "local-unknown")
    assert "unknown" in (unknown.selection_reason or "") and "explicit" in (unknown.selection_reason or "")
    assert unknown.training_provenance and unknown.training_provenance.initialization == "unknown"
    user = next(item for item in result.eligible_models if item.model_id == "local-user-smoke-in-name")
    assert user.training_provenance and user.training_provenance.optimizer_steps == 1
    assert user.training_provenance.evaluation_dataset_recorded
    assert user.training_provenance.evaluation_status == "none_attached"
    assert user.selection_basis == "default"  # no filename or low-step-count exclusion


@pytest.mark.parametrize("brief,expected", [
    ("Use local-a for this experiment", ["local-a"]),
    ("Please compare `local-a` and model.local-b", ["local-a", "local-b"]),
    ("I want to test the checkpoint local-a", ["local-a"]),
    ("Do not use local-a; use local-b", ["local-b"]),
    ("Use local-a instead of local-b", ["local-a"]),
    ("Use local-a; do not use local-a", []),
    ("I saw local-a in the catalog", []),
    ("Can you explain how to use local-a?", []),
    ("Why did you use local-a?", []),
    ("Don't compare local-a and local-b", []),
    ('Read labels containing "use local-a"', []),
    ("Use the label 'local-a' as the expected text", []),
    ("Use local-a-new", []),
    ("Use an engineering model", []),
    ("User request:\nCount people.\nUser clarification: Compare local-a and local-b", ["local-a", "local-b"]),
    ('Current app context:\n{"assistant":"Use local-a"}\nUser request:\nCount people', []),
])
def test_only_exact_affirmative_model_commands_authorize(brief: str, expected: list[str]) -> None:
    assert explicit_model_ids(brief, ["local-a", "local-b"]) == expected


def test_exact_request_enables_experiment_without_claiming_default_suitability(inventory: tuple[WorkspaceService, str, Path]) -> None:
    service, project_id, _ = inventory
    result = planning_options(service, project_id, request="Compare local-engineering and local-unknown")
    for identifier in ("local-engineering", "local-unknown"):
        entry = next(item for item in result.eligible_models if item.model_id == identifier)
        assert entry.selection_basis == "explicit_experiment"
        assert "generic goals" in (entry.selection_reason or "") or "unknown" in (entry.selection_reason or "")
    assert result.explicit_model_ids == ["local-engineering", "local-unknown"]
    assert not {"local-engineering", "local-unknown"} & {item.model_id for item in result.experimental_models}


def test_metadata_change_invalidates_selected_options(inventory: tuple[WorkspaceService, str, Path]) -> None:
    service, project_id, root = inventory
    saved = planning_options(service, project_id, request="Use local-user-smoke-in-name")
    path = root / "local-user-smoke-in-name" / "manifest.json"
    record = LocalDetectorManifest.model_validate_json(path.read_text())
    record.use_scope = "engineering_smoke"
    path.write_text(record.model_dump_json())
    with pytest.raises(ValueError, match="changed"):
        validate_current_options(service, saved, ["model.local-user-smoke-in-name"])


def test_forged_experiment_receipt_cannot_override_originating_brief(inventory: tuple[WorkspaceService, str, Path]) -> None:
    service, project_id, _ = inventory
    state = AgentStateStore(service)
    operation = state.begin(project_id, "Count people", "media", "owlv2-base-patch16")
    forged = planning_options(service, project_id, request="Use local-engineering")
    call = state.start_call(project_id, operation.id, "tool", "planning_options", {"project_id":project_id})
    state.finish_call(project_id, operation.id, call.id, forged.model_dump(mode="json"))
    before = service.get_project(project_id), service.annotations(project_id)
    with pytest.raises(AgentConflict, match="originating user brief"):
        state.record_options(project_id, operation.id, forged.snapshot_id)
    assert before == (service.get_project(project_id), service.annotations(project_id))
    assert not state.platform.plans(project_id)


def test_legacy_options_hash_and_pure_reconstruction_remain_unchanged() -> None:
    raw = {"schema_version":"0.1", "snapshot_id":"", "project_id":"old", "fixture_source":True,
        "detection_constraint":None, "eligible_models":[{"capability_id":"model.fixture-color-v1",
        "model_id":"fixture-color-v1", "adapter_id":"fixture-color-v1", "task_types":["detection"],
        "output_contract":"detections/v1", "vocabulary":"closed", "supported_classes":["pallet"],
        "synthetic":True, "readiness":"ready", "provenance_hashes":{}, "version":"1", "limitations":[]}], "blocked_options":[]}
    old_hash = hashlib.sha256(json.dumps({key:value for key,value in raw.items() if key != "snapshot_id"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    old = PlanningOptions.model_validate(raw)
    old.snapshot_id = old_hash
    assert options_digest(old) == old_hash
    with pytest.raises(ValidationError, match="Legacy options"):
        PlanningOptions.model_validate({**raw, "explicit_model_ids":["local-engineering"]})
    decision = PlanDecision(message="Historical reconstruction only", choices=[PatternChoice(use_case="custom", objects=["pallet"], metric="count_mae", target=.5,
        model_capability_id="model.fixture-color-v1", model_reason="Historical recorded option")])
    assert compile_decision(decision, "media", "unused", old).candidates


async def test_real_mcp_binds_options_to_saved_brief_without_executing_local_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "models"
    path = root / "local-engineering" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(manifest("local-engineering", use_scope="engineering_smoke", use_scope_evidence_ref="synthetic-test:1").model_dump_json())
    (path.parent / "model.safetensors").write_bytes(b"Never loaded: metadata protocol fixture")
    monkeypatch.setenv("VISION_MODELS_DIR", str(root))
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Experimental permission transport", "custom")
    before = service.get_project(project.id), service.annotations(project.id)
    async with connect_tools(str(tmp_path / "workspace"), AgentState()) as tools:
        await tools.start_run(project.id, "Use local-engineering for this experiment", "media", "owlv2-base-patch16")
        captured = PlanningOptions.model_validate(await tools.call("planning_options", {"project_id":project.id, "operation_id":tools.operation_id}))
        assert next(item for item in captured.eligible_models if item.model_id == "local-engineering").selection_basis == "explicit_experiment"
        await tools.control("agent_record_options", {"snapshot_id":captured.snapshot_id})
    assert before == (service.get_project(project.id), service.annotations(project.id))
    assert not service.events(project.id)
