"""Selection contracts for an installed closed-vocabulary YOLOX adapter.

Catalog fixtures exercise policy only; actual ONNX execution is verified separately.
"""
from pathlib import Path

import pytest

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from engine.platform import planning_options as module
from engine.service import WorkspaceService
from spec.capabilities import CapabilityManifest


def catalog(availability: str) -> CapabilityManifest:
    installed = availability == "installed"
    return CapabilityManifest.model_validate({
        "id": "model.yolox-s-onnx-coco", "name": "YOLOX-s", "kind": "model",
        "description": "Closed COCO detector", "availability": availability,
        "implemented": True, "installation_ready": installed, "callable": False,
        "task_types": ["detection"], "license": {"identifier": "Apache-2.0", "status": "declared"},
        "provenance": {"scope": "registry_metadata"}, "hardware": {},
        "install_method": "manual_weights", "readiness": {
            "state": "unchecked" if installed else "blocked", "reason": "No smoke receipt" if installed else "Weights missing",
            "checked_at": "2026-10-29T00:00:00Z", "evidence_scope": "prerequisites",
        },
    })


@pytest.mark.parametrize("label,allowed", [("person", True), ("forklift", False), ("pallet", False)])
def test_installed_yolox_is_selectable_only_for_its_declared_classes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str, allowed: bool,
) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Closed detector selection", "custom")
    monkeypatch.setattr(module, "model_catalog", lambda: [catalog("installed")])
    monkeypatch.setattr(module, "list_models", lambda: [{"id": "yolox-s-onnx-coco", "backend": "yolox-onnx"}])
    monkeypatch.setattr(module, "trained_classes", lambda _: ["person", "car"])
    options = module.planning_options(service, project.id)
    option = options.eligible_models[0]
    assert option.adapter_id == "yolox-onnx" and option.vocabulary == "closed"
    assert option.readiness == "unchecked" and option.training_provenance is not None
    assert option.training_provenance.evaluation_status == "none_attached"
    decision = PlanDecision(message="Test a compatible detector", choices=[PatternChoice.model_validate({
        "use_case": "custom", "objects": [label], "metric": "count_mae", "target": .5,
        "model_capability_id": option.capability_id, "model_reason": "Installed closed-vocabulary baseline",
    })])
    if not allowed:
        with pytest.raises(ValueError, match=label):
            compile_decision(decision, "media", "owlv2-base-patch16", options)
        return
    result = compile_decision(decision, "media", "owlv2-base-patch16", options)
    detector = next(block for block in result.candidates[0].blocks if block.type == "detect")
    assert detector.params["model"] == "yolox-s-onnx-coco"
    assert detector.params["classes"] == ["person"]


def test_requesting_yolox_does_not_authorize_installation_or_missing_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Missing detector", "custom")
    monkeypatch.setattr(module, "model_catalog", lambda: [catalog("available_to_install")])
    monkeypatch.setattr(module, "list_models", lambda: [{"id": "yolox-s-onnx-coco", "backend": "yolox-onnx"}])
    options = module.planning_options(service, project.id, request="Use yolox-s-onnx-coco to count people")
    assert not options.eligible_models
    assert options.blocked_options[0].reason == "Weights missing"
