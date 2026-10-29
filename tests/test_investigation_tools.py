"""Deterministic A0 tool tests; real fixture adapter, no planner or Apple dependency."""
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from pydantic import TypeAdapter, ValidationError

from engine.capabilities.models import _fixture, model_catalog
from engine.eval.protocol import read_configuration, save_configuration
from engine.eval.usage import read_usage
from engine.investigations.media import DevelopmentMedia, media_identifier
from engine.investigations.probes import Artifacts, transformed
from engine.investigations.store import InvestigationStore
from engine.investigations.tools import InvestigationTools, ToolOutcome, descriptor
from engine.investigations.workflows import construct_workflow
from engine.models.fixture import PALETTE
from engine.service import WorkspaceService
from spec.capabilities import CapabilityManifest
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment
from spec.investigation import BuilderAction, NextAction, RunProbe, WorkflowDecision

ACTION = TypeAdapter(BuilderAction)


class Harness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.service = WorkspaceService(tmp_path / "workspace")
        self.project = self.service.create_project("A0 software fixture", "custom")
        image = Image.new("RGB", (101, 80), "black")
        ImageDraw.Draw(image).rectangle((60, 20, 89, 59), fill=PALETTE["pallet"])
        path = tmp_path / "source.png"
        image.save(path)
        self.service.import_media(self.project.id, [str(path)])
        self.store = InvestigationStore(self.service)
        self.task = self.store.create(self.project.id, "Inspect actual synthetic geometry")
        self.tools = InvestigationTools(self.service, self.store)
        self.capability = _fixture()
        monkeypatch.setattr(self.tools, "_catalog", lambda: [self.capability])

    def perform(self, **raw: Any) -> Any:
        action = ACTION.validate_python(raw)
        state = self.store.get(self.project.id, self.task.id)
        cls = WorkflowDecision if action.type == "construct_workflow" else NextAction
        decision = cls(type="workflow_decision" if cls is WorkflowDecision else "next_action",
                       state_revision=state.revision, decision_summary="Software test action", action=action)
        call = self.store.start_model_call(self.project.id, self.task.id, {}, "scripted-software-test")
        self.store.finish_model_call(self.project.id, self.task.id, call.id,
                                    response=decision.model_dump(mode="json"))
        receipt = self.store.reserve_action(self.project.id, self.task.id, decision)
        if action.type == "construct_workflow":
            outcome = construct_workflow(self.service, self.store, self.project.id, self.task.id, receipt.id, action)
        elif action.type == "prepare_workflow":
            outcome = ToolOutcome(payload={"schema_ready": True, "executed": False})
        else:
            outcome = self.tools.execute(self.project.id, self.task.id, receipt.id, action)
        return self.store.complete_action(self.project.id, self.task.id, receipt.id, outcome.payload,
                                         status=outcome.status, error=outcome.error)

    def probe_args(self) -> dict[str, Any]:
        # This helper owns the generated color rectangle; normal imports remain
        # nonfixture until a software test explicitly establishes their origin.
        project = self.service.get_project(self.project.id)
        project.fixture, project.synthetic = True, True
        project.data_origin = "Generated color rectangles for software tests"
        self.service.repository.save(project)
        inspected = self.perform(type="inspect_capability", capability_id=self.capability.id)
        inventory = self.perform(type="inspect_media")
        item = inventory.payload["items"][0]
        return {"type": "run_probe", "capability_id": self.capability.id,
            "inspected_descriptor_hash": inspected.payload["descriptor"]["descriptor_hash"],
            "media_id": item["media_id"], "source_sha256": item["source_sha256"],
            "request": {"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}}


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


def test_real_probe_transform_geometry_identity_and_no_project_effects(harness: Harness) -> None:
    args = harness.probe_args()
    root = harness.service.root(harness.project.id)
    annotations = (root / "annotations.json").read_bytes()
    project = (root / "project.json").read_bytes()
    args["transforms"] = [{"type": "crop", "box": [.5, 0, 1, 1]},
                          {"type": "resize", "width": 102, "height": 160}]
    observed = harness.perform(**args)
    assert observed.status == "completed", observed.error
    payload = observed.payload
    assert payload["executed"] is True and payload["total_items"] == 1
    assert payload["input_size"] == [102, 160]
    assert payload["input_to_source"] == [50 / 101, 0, 51 / 101, 1]
    assert payload["items"][0]["source_box"] == pytest.approx([60 / 101, .25, 90 / 101, .75], abs=.02)
    assert payload["identity_refs"][0]["model_id"] == "fixture-color-v1"
    assert payload["identity_refs"][0]["identity_scope"] == "synthetic_code"
    artifacts = Artifacts(harness.store.root(harness.project.id, harness.task.id))
    raw = json.loads(artifacts.read(payload["result_artifact"]))
    assert raw["result"]["input_pixels_sha256"] == payload["input_pixels_sha256"]
    assert raw["result"]["detections"][0]["label"] == "pallet"
    assert payload["timing"]["total_ms"] >= payload["timing"]["adapter"]["total_ms"] > 0
    assert len(read_usage(root).uses) >= 3
    assert annotations == (root / "annotations.json").read_bytes()
    assert project == (root / "project.json").read_bytes()
    assert not harness.service.events(harness.project.id)


def test_transform_order_is_material_and_uses_integer_pixel_boundaries(harness: Harness) -> None:
    args = harness.probe_args()
    source = DevelopmentMedia(harness.service, harness.project.id).resolve(args["media_id"])
    args["transforms"] = [{"type": "resize", "width": 7, "height": 5},
                          {"type": "crop", "box": [.5, 0, 1, 1]}]
    image, mapping = transformed(source.image, RunProbe.model_validate(args))
    assert image.size == (4, 5) and mapping == (3 / 7, 0, 4 / 7, 1)
    args["transforms"].reverse()
    image, mapping = transformed(source.image, RunProbe.model_validate(args))
    assert image.size == (7, 5) and mapping == (50 / 101, 0, 51 / 101, 1)


def test_inspection_reuses_saved_values_and_tampering_fails(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = harness.perform(**harness.probe_args())
    monkeypatch.setattr("engine.investigations.probes.run_inference", lambda *_a, **_k: pytest.fail("Inspection reran inference"))
    inspected = harness.perform(type="inspect_observation", observation_id=observed.id, view="geometry")
    assert inspected.status == "completed" and inspected.payload["executed"] is False
    assert inspected.payload["items"][0]["source_box"] == observed.payload["items"][0]["source_box"]
    image = harness.perform(type="inspect_observation", observation_id=observed.id, view="image")
    assert image.status == "completed" and image.payload["pixels_visible_to_planner"] is False
    ref = observed.payload["result_artifact"]
    (harness.store.root(harness.project.id, harness.task.id) / "artifacts" / ref["artifact_id"]).write_text("{}")
    failed = harness.perform(type="inspect_observation", observation_id=observed.id)
    assert failed.status == "failed" and "content changed" in failed.error["message"]


def test_failed_adapter_retains_exposure_and_explicit_failure(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    args = harness.probe_args()
    def fail(*_a: Any, **_k: Any) -> Any:
        assert read_usage(harness.service.root(harness.project.id)).uses
        raise RuntimeError("Deliberate backend failure")
    monkeypatch.setattr("engine.investigations.probes.run_inference", fail)
    observed = harness.perform(**args)
    assert observed.status == "failed" and observed.payload["executed"] is True
    assert observed.error["code"] == "adapter_failed"
    assert "result_artifact" not in observed.payload
    inspected = harness.perform(type="inspect_observation", observation_id=observed.id, view="error")
    assert inspected.status == "completed"
    assert inspected.payload["observed_error"] == observed.error


@pytest.mark.parametrize("mutation", ["descriptor", "source", "capability"])
def test_stale_or_mismatched_probe_never_executes(harness: Harness, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    args = harness.probe_args()
    if mutation == "descriptor":
        harness.capability.description += " revised"
    elif mutation == "source":
        args["source_sha256"] = "0" * 64
    else:
        args["capability_id"] = "model.apple-vision"
    monkeypatch.setattr("engine.investigations.probes.run_inference", lambda *_a, **_k: pytest.fail("Unauthorized inference"))
    observed = harness.perform(**args)
    assert observed.status == "failed" and observed.payload["executed"] is False
    assert not read_usage(harness.service.root(harness.project.id)).uses


def reserve_all(harness: Harness) -> None:
    root = harness.service.root(harness.project.id)
    dataset = harness.service.annotations(harness.project.id)
    config = read_configuration(root, dataset)
    save_configuration(root, dataset, EvaluationConfigurationUpdate(expected_revision=config.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, split="acceptance", scene_group="reserved", data_origin=row.data_origin)
                     for row in config.images], policy=config.policy))


def test_acceptance_reservation_blocks_probe_and_saved_artifact_shortcut(harness: Harness) -> None:
    args = harness.probe_args()
    observed = harness.perform(**args)
    reserve_all(harness)
    inventory = harness.perform(type="inspect_media")
    assert inventory.payload["total_items"] == 0
    rejected = harness.perform(**args)
    assert rejected.status == "failed" and rejected.payload["executed"] is False
    inspection = harness.perform(type="inspect_observation", observation_id=observed.id, view="image")
    assert inspection.status == "failed"


def test_opaque_id_is_project_scoped_and_paths_are_not_accepted(harness: Harness) -> None:
    args = harness.probe_args()
    project = harness.service.create_project("Different project")
    assert args["media_id"] not in DevelopmentMedia(harness.service, project.id).identifiers()
    assert media_identifier(project.id, "media/test.png") != media_identifier(harness.project.id, "media/test.png")
    with pytest.raises(ValidationError):
        RunProbe.model_validate({**args, "media_id": "/tmp/source.png"})
    with pytest.raises(ValidationError):
        RunProbe.model_validate({**args, "endpoint": "http://localhost:9999"})


def test_capability_search_is_metadata_only_and_descriptor_hash_ignores_check_time(harness: Harness) -> None:
    found = harness.perform(type="discover_capabilities", query="synthetic", kind="model", task_type="detection")
    assert found.payload["total_items"] == 1
    assert "probe_request_schemas" not in found.payload["items"][0]
    assert harness.perform(type="discover_capabilities", query="astronomy spectroscopy").payload["total_items"] == 0
    before = descriptor(harness.capability)
    harness.capability.readiness.checked_at = "different-check-time"
    for evidence in harness.capability.readiness.evidence:
        evidence.observed_at = "different-check-time"
    after = descriptor(harness.capability)
    assert before["descriptor_hash"] == after["descriptor_hash"]
    assert after["class_vocabulary"] == list(PALETTE)
    assert after["probe_request_schemas"][0]["properties"]["model_id"]["const"] == "fixture-color-v1"
    inspected = harness.perform(type="inspect_capability", capability_id=harness.capability.id)
    view = inspected.payload["model_view"]
    full = inspected.payload["descriptor"]
    assert view["descriptor_hash"] == full["descriptor_hash"]
    assert view["probe_request_schemas"] == full["probe_request_schemas"]
    assert view["class_vocabulary"] == full["class_vocabulary"]
    assert "probe_output_schema" not in view


@pytest.mark.parametrize("identifier,kind,tasks,implemented,installed,availability,readiness,eligible,role", [
    ("model.apple-vision", "model", ["ocr", "barcode"], True, True, "installed", "unchecked", True, "typed_adapter_model"),
    ("model.apple-vision", "model", ["ocr"], True, True, "installed", "ready", True, "typed_adapter_model"),
    ("model.apple-vision", "model", ["ocr"], True, False, "available_to_install", "blocked", False, "typed_adapter_model"),
    ("model.apple-vision", "model", ["ocr"], False, False, "unsupported", "unsupported", False, "typed_adapter_model"),
    ("model.apple-vision", "model", ["planning"], True, True, "installed", "ready", False, "catalogue_model"),
    ("model.unregistered", "model", ["detection"], True, True, "installed", "ready", False, "catalogue_model"),
    ("block.detect", "tool", ["detection"], True, True, "installed", "unchecked", False, "graph_block"),
    ("block.unregistered", "tool", ["detection"], False, False, "unsupported", "unsupported", False, "catalogue_tool"),
    ("tool.example", "tool", ["detection"], True, True, "installed", "ready", False, "catalogue_tool"),
])
def test_every_discovery_role_uses_descriptor_probe_prerequisites(harness: Harness,
        identifier: str, kind: str, tasks: list[str], implemented: bool, installed: bool,
        availability: str, readiness: str, eligible: bool, role: str) -> None:
    raw = harness.capability.model_dump(mode="json")
    raw.update(id=identifier, kind=kind, task_types=tasks, implemented=implemented,
               installation_ready=installed, availability=availability, callable=False)
    raw["readiness"]["state"] = readiness
    harness.capability = CapabilityManifest.model_validate(raw)
    before = descriptor(harness.capability)
    found = harness.perform(type="discover_capabilities")
    row = found.payload["items"][0]
    assert row["probe_eligible"] is eligible
    assert row["probe_eligible"] == before["probe_eligible"]
    assert row["probe_tasks"] == before["probe_tasks"]
    assert row["execution_role"] == role
    assert row["matched_terms"] == row["unmatched_terms"] == []
    inspected = harness.perform(type="inspect_capability", capability_id=identifier)
    assert inspected.payload["model_view"]["probe_eligible"] is eligible
    assert inspected.payload["descriptor"]["descriptor_hash"] == before["descriptor_hash"]
    assert "execution_role" not in inspected.payload["descriptor"]  # Discovery-only detail preserves hash content.


@pytest.mark.parametrize("fixture_project,installed", [(False, True), (True, True), (True, False)])
def test_discovery_fixture_gate_combines_project_and_machine_eligibility(harness: Harness,
        fixture_project: bool, installed: bool) -> None:
    project = harness.service.get_project(harness.project.id)
    project.fixture = fixture_project
    harness.service.repository.save(project)
    harness.capability.installation_ready = installed
    harness.capability.callable = False
    before = descriptor(harness.capability)
    found = harness.perform(type="discover_capabilities", query="fixture")
    row = found.payload["items"][0]
    assert row["execution_role"] == "typed_adapter_model" and row["probe_tasks"] == ["detection"]
    assert row["probe_eligible"] is (fixture_project and installed)
    inspected = harness.perform(type="inspect_capability", capability_id=harness.capability.id)
    assert row["probe_eligible"] == inspected.payload["model_view"]["probe_eligible"]
    assert inspected.payload["descriptor"]["descriptor_hash"] == before["descriptor_hash"]


def test_search_echoes_exact_filters_and_unmatched_terms_without_task_routing(harness: Harness,
        monkeypatch: pytest.MonkeyPatch) -> None:
    reader = next(item for item in model_catalog() if item.id == "model.apple-vision")
    monkeypatch.setattr(harness.tools, "_catalog", lambda: [harness.capability, reader])
    found = harness.perform(type="discover_capabilities", query="item code detection", task_type="detection")
    assert found.payload["query"] == "item code detection"
    assert found.payload["active_filters"] == {"kind": None, "task_type": "detection"}
    assert found.payload["total_items"] == 1
    row = found.payload["items"][0]
    assert row["capability_id"] == "model.fixture-color-v1"
    assert row["matched_terms"] == ["detection"] and row["unmatched_terms"] == ["code", "item"]
    saved = harness.perform(type="inspect_observation", observation_id=found.id)
    assert saved.payload["query"] == found.payload["query"]
    assert saved.payload["active_filters"] == found.payload["active_filters"]
    empty = harness.perform(type="discover_capabilities", query="ocr", kind="tool", task_type="detection")
    assert empty.payload["items"] == [] and empty.payload["total_items"] == 0
    assert empty.payload["active_filters"] == {"kind": "tool", "task_type": "detection"}


@pytest.mark.parametrize("capability,model,fragment", [
    ("block.detect", "block.detect", "not a graph block"),
    ("model.fixture-color-v1", "model.fixture-color-v1", "'model.' + request.model_id"),
    ("model.apple-vision", "fixture-color-v1", "does not match"),
])
def test_probe_namespace_errors_point_to_inspected_request_contract(harness: Harness,
        monkeypatch: pytest.MonkeyPatch, capability: str, model: str, fragment: str) -> None:
    args = harness.probe_args()
    args["capability_id"], args["request"]["model_id"] = capability, model
    monkeypatch.setattr(DevelopmentMedia, "expose", lambda *_a, **_k: pytest.fail("Rejected probe exposed pixels"))
    monkeypatch.setattr("engine.investigations.probes.run_inference", lambda *_a, **_k: pytest.fail("Rejected probe ran inference"))
    observed = harness.perform(**args)
    assert observed.status == "failed" and observed.payload["executed"] is False
    assert fragment in observed.error["message"]
    assert "probe_request_schemas" in observed.error["message"]
    assert not read_usage(harness.service.root(harness.project.id)).uses


def test_broad_live_search_matches_actual_reader_metadata(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = next(item for item in model_catalog() if item.id == "model.apple-vision")
    monkeypatch.setattr(harness.tools, "_catalog", lambda: [harness.capability, reader])
    found = harness.perform(type="discover_capabilities",
        query="image processing, item code extraction, OCR, computer vision")
    assert found.status == "completed"
    assert found.payload["items"][0]["capability_id"] == "model.apple-vision"
    assert found.payload["items"][0]["matched_terms"] == ["ocr", "vision"]
    assert found.payload["items"][0]["match_score"] > 0
    assert "match any" in found.payload["search_semantics"]
    assert not found.payload["executed"]


def test_search_normalizes_case_punctuation_and_ignores_function_words(harness: Harness) -> None:
    first = harness.perform(type="discover_capabilities", query="SYNTHETIC, color/fixture!")
    second = harness.perform(type="discover_capabilities", query="the synthetic and COLOR fixture")
    assert first.payload["items"] == second.payload["items"]
    assert first.payload["query_terms"] == second.payload["query_terms"] == ["color", "fixture", "synthetic"]
    for query in ("the and of", "?!", "astronomy spectroscopy", "synthet"):
        found = harness.perform(type="discover_capabilities", query=query)
        assert found.payload["total_items"] == 0
    assert harness.perform(type="discover_capabilities", query="  ").payload["total_items"] == 1


def test_search_relevance_pagination_and_filters_are_stable(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    records = [harness.capability.model_copy(update={"id": "model." + identifier,
        "name": "Analyzer", "description": description}) for identifier, description in (
            ("zeta", "alpha beta"), ("gamma", "alpha beta delta"), ("eta", "alpha beta"))]
    records.append(harness.capability.model_copy(update={"id": "tool.delta", "kind": "tool",
        "name": "Analyzer", "description": "alpha beta delta", "task_types": ["geometry"]}))
    monkeypatch.setattr(harness.tools, "_catalog", lambda: records)
    query = "alpha, beta, delta"
    first = harness.perform(type="discover_capabilities", query=query, kind="model", task_type="detection", limit=1)
    assert first.payload["items"][0]["capability_id"] == "model.gamma"
    records.reverse()  # Pagination must not depend on registry enumeration order.
    second = harness.perform(type="discover_capabilities", query="ALPHA beta DELTA", kind="model",
        task_type="detection", limit=1, cursor=first.payload["next_cursor"])
    assert second.status == "completed"
    assert second.payload["items"][0]["capability_id"] == "model.eta"
    third = harness.perform(type="discover_capabilities", query=query, kind="model", task_type="detection",
        limit=1, cursor=second.payload["next_cursor"])
    assert third.payload["items"][0]["capability_id"] == "model.zeta"
    assert not third.payload["truncated"] and third.payload["next_cursor"] is None
    assert first.payload["total_items"] == second.payload["total_items"] == third.payload["total_items"] == 3
    assert harness.perform(type="discover_capabilities", query=query, kind="model", task_type="geometry").payload["total_items"] == 0


def test_unknown_filter_exposes_taxonomy_and_labelled_lexical_suggestions(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = next(item for item in model_catalog() if item.id == "model.apple-vision")
    monkeypatch.setattr(harness.tools, "_catalog", lambda: [harness.capability, reader])
    found = harness.perform(type="discover_capabilities", query="code reader", task_type="image_analysis")
    payload = found.payload
    assert payload["items"] == [] and payload["total_items"] == 0
    assert payload["available_kinds"] == ["model"]
    assert payload["available_task_types"] == ["barcode", "detection", "ocr"]
    assert payload["filter_diagnostics"][0]["code"] == "unknown_filter_value"
    assert payload["filter_diagnostics"][0]["requested"] == "image_analysis"
    assert payload["suggestion_ignored_filters"] == ["task_type"]
    suggestion = payload["suggestions"][0]
    assert suggestion["capability_id"] == "model.apple-vision"
    assert suggestion["suggestion_type"] == "approximate_metadata" and suggestion["exact_query_match"] is False
    assert {"query_term": "code", "metadata_term": "barcode"} in suggestion["related_terms"]
    assert suggestion["matched_terms"] == [] and suggestion["unmatched_terms"] == ["code", "reader"]
    assert suggestion["execution_role"] == "typed_adapter_model" and suggestion["probe_tasks"] == ["ocr", "barcode"]
    assert len(payload["suggestions"]) <= 3 and "readiness" in suggestion
    captured = harness.perform(type="inspect_observation", observation_id=found.id)
    assert captured.status == "completed" and captured.payload["source_total_items"] == 0
    assert captured.payload["items"][0]["record_type"] == "catalog_suggestion"
    assert captured.payload["filter_diagnostics"] == payload["filter_diagnostics"]


def test_zero_match_inventory_suggestions_do_not_become_query_hits(harness: Harness) -> None:
    found = harness.perform(type="discover_capabilities", query="zzzzzzzz", kind="model", task_type="detection")
    assert found.payload["total_items"] == 0 and found.payload["items"] == []
    assert not found.payload["suggestion_ignored_filters"]
    suggestion = found.payload["suggestions"][0]
    assert suggestion["suggestion_type"] == "inventory" and suggestion["suggestion_score"] == 0
    assert not suggestion["exact_query_match"] and suggestion["kind"] == "model"
    assert "detection" in suggestion["task_types"]


def test_generic_similarity_is_not_a_reader_alias_router(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    item = harness.capability.model_copy(update={"id": "model.arbitrary", "name": "Arbitrary function",
        "description": "Computes rotations and tokenizations"})
    monkeypatch.setattr(harness.tools, "_catalog", lambda: [item])
    found = harness.perform(type="discover_capabilities", query="rotation tokenization")
    assert not found.payload["items"]
    suggestion = found.payload["suggestions"][0]
    assert suggestion["suggestion_type"] == "approximate_metadata"
    assert {"query_term": "rotation", "metadata_term": "rotations"} in suggestion["related_terms"]


def test_saved_media_and_descriptor_inspection_do_not_repeat_discovery(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    descriptor = harness.perform(type="inspect_capability", capability_id=harness.capability.id)
    media = harness.perform(type="inspect_media", representation="pixels")
    monkeypatch.setattr(harness.tools, "_catalog", lambda: pytest.fail("Saved inspection repeated catalogue discovery"))
    capability = harness.perform(type="inspect_observation", observation_id=descriptor.id)
    assert capability.status == "completed" and capability.payload["items"][0]["descriptor_hash"] == descriptor.payload["descriptor"]["descriptor_hash"]
    values = harness.perform(type="inspect_observation", observation_id=media.id)
    assert values.status == "completed" and values.payload["items"] == media.payload["items"]
    pixels = harness.perform(type="inspect_observation", observation_id=media.id, view="image")
    assert pixels.status == "completed" and pixels.payload["artifact_refs"] == media.payload["artifact_refs"]
    assert pixels.payload["pixels_visible_to_planner"] is False
    reserve_all(harness)
    assert harness.perform(type="inspect_observation", observation_id=media.id).status == "failed"


def construct_actual_fixture_preview(harness: Harness) -> Any:
    harness.project = harness.service.create_project("Saved workflow geometry fixture", "custom")
    harness.service.demo(harness.project.id)
    harness.task = harness.store.create(harness.project.id, "Inspect actual fixture workflow results")
    harness.perform(type="inspect_capability", capability_id=harness.capability.id)
    harness.perform(type="prepare_workflow", summary="Load actual graph schema")
    identifiers = DevelopmentMedia(harness.service, harness.project.id).identifiers()[:2]
    observation = harness.perform(type="construct_workflow", media_ids=identifiers, graph={
        "name": "Synthetic geometry", "metric": "count_mae", "target": .5, "nodes": [
            {"type": "frame_sample", "id": "sample", "fps": 2},
            {"type": "crop", "id": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]},
            {"type": "resize", "id": "resize", "image": "$crop.image", "width": 160, "height": 160},
            {"type": "detect", "id": "det", "image": "$resize.image", "classes": ["pallet"],
             "min_confidence": .4, "model_capability_id": "model.fixture-color-v1", "model_reason": "Software fixture only"},
            {"type": "count_per_zone", "id": "count", "dets": "$det.dets", "include_unassigned": False}]})
    assert observation.status == "completed", observation.error
    return observation


def test_workflow_inspection_pages_actual_frames_nodes_and_geometry(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    saved = construct_actual_fixture_preview(harness)
    monkeypatch.setattr("engine.investigations.workflows.run_pipeline", lambda *_a, **_k: pytest.fail("Inspection reran preview"))
    rows, cursor = [], None
    for _ in range(10):
        page = harness.perform(type="inspect_observation", observation_id=saved.id, limit=4, cursor=cursor)
        assert page.status == "completed", page.error
        assert page.payload["workflow_revision_id"] == saved.payload["workflow_revision_id"]
        assert page.payload["spec_hash"] == page.payload["preview_spec_hash"] == saved.payload["spec_hash"]
        assert page.payload["executed"] is False
        rows.extend(page.payload["items"])
        cursor = page.payload["next_cursor"]
        if cursor is None:
            break
    assert cursor is None and len(rows) == page.payload["total_items"]
    assert len({row["item_id"] for row in rows}) == len(rows)
    assert [row["count"] for row in rows if row["record_type"] == "frame_count"] == [frame["counts"]["all"] for frame in saved.payload["preview"]["frames"]]
    nodes = [row for row in rows if row["record_type"] == "inference_summary"]
    assert len(nodes) == 2 and all(row["block_id"] == "det" and row["input_to_source"] == [0, 0, .5, 1] for row in nodes)
    geometry = harness.perform(type="inspect_observation", observation_id=saved.id, view="geometry")
    assert geometry.status == "completed" and geometry.payload["total_items"] > 0
    assert all(row["source_box"][2] <= .5 for row in geometry.payload["items"])
    assert str(harness.service.root(harness.project.id)) not in json.dumps(geometry.payload)
    reserve_all(harness)
    assert harness.perform(type="inspect_observation", observation_id=saved.id).status == "failed"


def test_workflow_saved_preview_tampering_is_rejected(harness: Harness) -> None:
    saved = construct_actual_fixture_preview(harness)
    reference = saved.payload["preview_artifact"]
    path = harness.store.root(harness.project.id, harness.task.id) / "artifacts" / reference["artifact_id"]
    path.write_text("{}")
    inspected = harness.perform(type="inspect_observation", observation_id=saved.id)
    assert inspected.status == "failed" and "content changed" in inspected.error["message"]


def test_media_pagination_and_explicit_pixel_visibility(harness: Harness, tmp_path: Path) -> None:
    for index in range(3):
        path = tmp_path / f"extra-{index}.png"
        Image.new("RGB", (10, 10), (index, index, index)).save(path)
        harness.service.import_media(harness.project.id, [str(path)])
    first = harness.perform(type="inspect_media", limit=3)
    assert first.payload["total_items"] == 4 and first.payload["truncated"]
    second = harness.perform(type="inspect_media", cursor=first.payload["next_cursor"], representation="pixels")
    assert second.payload["returned_items"] == 1 and not second.payload["truncated"]
    assert second.payload["pixels_visible_to_planner"] is False
    assert second.payload["artifact_refs"][0]["mime_type"] == "image/png"
    assert str(harness.service.root(harness.project.id)) not in json.dumps(second.payload)


def test_reserved_identical_pixels_cannot_be_reimported_as_development(harness: Harness, tmp_path: Path) -> None:
    original = Path(harness.service.get_project(harness.project.id).media[0])
    duplicate = tmp_path / "duplicate.bmp"
    with Image.open(original) as image:
        image.save(duplicate)
    reserve_all(harness)
    harness.service.import_media(harness.project.id, [str(duplicate)])
    result = harness.perform(type="inspect_media", representation="pixels")
    assert result.status == "failed" and "reserved acceptance content" in result.error["message"]
    assert not read_usage(harness.service.root(harness.project.id)).uses


def test_values_pagination_uses_actual_saved_outputs(harness: Harness, tmp_path: Path) -> None:
    image = Image.new("RGB", (100, 100), "black")
    draw = ImageDraw.Draw(image)
    for y in range(5):
        for x in range(5):
            draw.rectangle((x * 20, y * 20, x * 20 + 5, y * 20 + 5), fill=PALETTE["pallet"])
    source = Path(harness.service.get_project(harness.project.id).media[0])
    image.save(source)
    observed = harness.perform(**harness.probe_args())
    assert observed.payload["total_items"] == 25 and observed.payload["returned_items"] == 20
    assert observed.payload["truncated"] is True
    page = harness.perform(type="inspect_observation", observation_id=observed.id,
                           cursor=observed.payload["next_cursor"])
    assert page.status == "completed", page.error
    assert page.payload["total_items"] == 25 and page.payload["returned_items"] == 5
    assert not page.payload["truncated"]
    assert not {row["item_id"] for row in page.payload["items"]} & {row["item_id"] for row in observed.payload["items"]}


def test_unreserved_action_and_changed_arguments_are_rejected(harness: Harness) -> None:
    outcome = harness.tools.execute(harness.project.id, harness.task.id, "0" * 32,
                                   ACTION.validate_python({"type": "inspect_media"}))
    assert outcome.status == "failed" and "reserved action" in outcome.error["message"]
    assert not (harness.store.root(harness.project.id, harness.task.id) / "artifacts").exists()


def test_source_changed_during_adapter_discards_completed_result(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.investigations.probes import run_inference
    args = harness.probe_args()
    def change_source(*pos: Any, **kw: Any) -> Any:
        result = run_inference(*pos, **kw)
        Image.new("RGB", (101, 80), "white").save(harness.service.get_project(harness.project.id).media[0])
        return result
    monkeypatch.setattr("engine.investigations.probes.run_inference", change_source)
    observed = harness.perform(**args)
    assert observed.status == "failed" and observed.payload["executed"] is True
    assert observed.payload["execution_status"] == "completed_result_discarded"
    assert observed.error["code"] == "input_changed" and "result_artifact" not in observed.payload


@pytest.mark.parametrize("synthetic", [False, True])
def test_fixture_adapter_is_blocked_for_nonfixture_imports_before_exposure(harness: Harness, monkeypatch: pytest.MonkeyPatch, synthetic: bool) -> None:
    project = harness.service.get_project(harness.project.id)
    project.synthetic = synthetic
    harness.service.repository.save(project)
    assert not project.fixture
    discovery = harness.perform(type="discover_capabilities", query="fixture")
    assert discovery.payload["items"][0]["probe_eligible"] is False
    assert discovery.payload["items"][0]["project_eligibility"]["requires_fixture_project"] is True
    inspected = harness.perform(type="inspect_capability", capability_id=harness.capability.id)
    # Machine availability remains separately identifiable; project permission is
    # effective in the model-visible view and never changes the descriptor hash.
    assert inspected.payload["descriptor"]["probe_eligible"] is True
    assert inspected.payload["model_view"]["probe_eligible"] is False
    assert inspected.payload["model_view"]["project_eligibility"]["allowed"] is False
    assert inspected.payload["descriptor"]["descriptor_hash"] == descriptor(harness.capability)["descriptor_hash"]
    media = harness.perform(type="inspect_media").payload["items"][0]
    monkeypatch.setattr(DevelopmentMedia, "expose", lambda *_a, **_k: pytest.fail("Rejected fixture probe exposed pixels"))
    monkeypatch.setattr("engine.investigations.probes.run_inference", lambda *_a, **_k: pytest.fail("Rejected fixture probe ran inference"))
    result = harness.perform(type="run_probe", capability_id=harness.capability.id,
        inspected_descriptor_hash=inspected.payload["descriptor"]["descriptor_hash"], media_id=media["media_id"],
        source_sha256=media["source_sha256"], request={"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4})
    assert result.status == "failed" and result.payload["executed"] is False
    assert "nonfixture" in result.error["message"]
    assert not read_usage(harness.service.root(harness.project.id)).uses
    assert not (harness.store.root(harness.project.id, harness.task.id) / "artifacts").exists()


def test_fixture_permission_revoked_after_inspection_is_rechecked(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    args = harness.probe_args()
    inspected = next(row for row in harness.store.observations(harness.project.id, harness.task.id)
                     if row.result_type == "inspect_capability")
    assert inspected.payload["model_view"]["probe_eligible"] is True
    project = harness.service.get_project(harness.project.id)
    project.fixture = False
    assert project.synthetic is True
    harness.service.repository.save(project)
    monkeypatch.setattr(DevelopmentMedia, "expose", lambda *_a, **_k: pytest.fail("Stale project permission exposed pixels"))
    result = harness.perform(**args)
    assert result.status == "failed" and result.payload["executed"] is False
    assert "nonfixture" in result.error["message"]
    assert not read_usage(harness.service.root(harness.project.id)).uses
