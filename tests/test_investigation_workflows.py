"""Actual synthetic workflow execution and task-owned draft boundary checks."""
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from engine.capabilities.models import _fixture
from engine.eval.protocol import read_configuration, save_configuration
from engine.eval.usage import read_usage
from engine.investigations.media import media_identifier
from engine.investigations.probes import Artifacts
from engine.investigations.store import InvestigationStore
from engine.investigations.tools import InvestigationTools
from engine.investigations.workflows import construct_workflow
from engine.service import WorkspaceService
from spec.authoring import GraphCandidate
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment
from spec.investigation import BuilderAction, ConstructWorkflow, NextAction, WorkflowDecision


def graph(*, zones: bool = False, events: bool = False) -> GraphCandidate:
    nodes: list[dict[str, Any]] = [
        {"type": "frame_sample", "id": "sample", "fps": 2},
        {"type": "crop", "id": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]},
        {"type": "resize", "id": "resize", "image": "$crop.image", "width": 320, "height": 400},
        {"type": "detect", "id": "det", "image": "$resize.image", "classes": ["pallet"],
         "min_confidence": .4, "model_capability_id": "model.fixture-color-v1",
         "model_reason": "Synthetic software fixture; no measured model quality"}]
    if zones:
        nodes.append({"type": "zone_filter", "id": "zones", "dets": "$det.dets", "zone_ids": ["A"]})
    nodes.append({"type": "count_per_zone", "id": "count", "dets": "$zones.dets" if zones else "$det.dets", "include_unassigned": False})
    if events:
        nodes.extend([{"type": "rule", "id": "rule", "counts": "$count.counts", "operator": ">=", "threshold": 1, "hold_seconds": 0},
                      {"type": "sink_event", "id": "event", "event": "$rule.event"}])
    return GraphCandidate.model_validate({"name": "Model-chosen software experiment", "nodes": nodes,
                                         "metric": "count_mae", "target": .5})


class Harness:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.service = WorkspaceService(tmp_path / "workspace")
        self.project_id = self.service.create_project("Workflow software fixture", "custom").id
        self.service.demo(self.project_id)
        self.store = InvestigationStore(self.service)
        self.task_id = self.store.create(self.project_id, "Investigate a useful visual application").id
        self.tools = InvestigationTools(self.service, self.store)
        self.capability = _fixture()
        monkeypatch.setattr(InvestigationTools, "_catalog", lambda _self: [self.capability])
        self.media_ids = [media_identifier(self.project_id, f"media/synthetic-{index:02d}.png") for index in (2, 1)]

    @property
    def root(self) -> Path:
        return self.service.root(self.project_id)

    def reserve(self, action: Any) -> Any:
        state = self.store.get(self.project_id, self.task_id)
        cls = WorkflowDecision if isinstance(action, ConstructWorkflow) else NextAction
        decision = cls.model_validate({"type": "workflow_decision" if cls is WorkflowDecision else "next_action",
            "state_revision": state.revision, "decision_summary": "Scripted persistence test, not planner evidence",
            "action": action.model_dump(mode="json")})
        call = self.store.start_model_call(self.project_id, self.task_id, {"test_stub": True}, "scripted-test-model")
        self.store.finish_model_call(self.project_id, self.task_id, call.id, decision.model_dump(mode="json"))
        return self.store.reserve_action(self.project_id, self.task_id, decision)

    def inspect(self) -> Any:
        action = TypeAdapter(BuilderAction).validate_python({"type": "inspect_capability", "capability_id": self.capability.id})
        receipt = self.reserve(action)
        outcome = self.tools.execute(self.project_id, self.task_id, receipt.id, action)
        assert outcome.status == "completed", outcome.error
        return self.store.complete_action(self.project_id, self.task_id, receipt.id, outcome.payload)

    def prepare(self) -> None:
        action = TypeAdapter(BuilderAction).validate_python({"type": "prepare_workflow", "summary": "Load the graph schema"})
        receipt = self.reserve(action)
        self.store.complete_action(self.project_id, self.task_id, receipt.id, {"schema_ready": True})

    def action(self, value: GraphCandidate | None = None, **extra: Any) -> ConstructWorkflow:
        return ConstructWorkflow(type="construct_workflow", graph=value or graph(), media_ids=self.media_ids, **extra)

    def construct(self, action: ConstructWorkflow | None = None) -> Any:
        self.prepare()
        proposal = action or self.action()
        receipt = self.reserve(proposal)
        outcome = construct_workflow(self.service, self.store, self.project_id, self.task_id, receipt.id, proposal)
        observation = self.store.complete_action(self.project_id, self.task_id, receipt.id, outcome.payload,
                                                status=outcome.status, error=outcome.error)
        assert observation.status == outcome.status, observation.error
        return observation


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


def test_actual_preview_uses_exact_selected_pixels_and_keeps_project_unchanged(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    harness.inspect()
    before = {name: (harness.root / name).read_bytes() for name in ["project.json", "annotations.json"]}
    monkeypatch.setattr("agent.graph_intent.validate_graph_intent", lambda *_: pytest.fail("A0 must not use task regex guards"))
    observation = harness.construct()
    assert observation.status == "completed", observation.error
    payload = observation.payload
    assert payload["validated"] is True and payload["preview_success"] is True and payload["executed"] is True
    assert payload["spec_hash"] == payload["preview_spec_hash"]
    assert payload["preview_media_ids"] == harness.media_ids
    frames = payload["preview"]["frames"]
    assert len(frames) == 2 and [frame["counts"]["all"] for frame in frames] == [4, 2]
    assert all(frame["inferences"][0]["result"]["identity"]["identity_scope"] == "synthetic_code" for frame in frames)
    assert all(frame["inferences"][0]["input_to_frame"] == [0, 0, .5, 1] for frame in frames)
    assert all(frame["inferences"][0]["result"]["input_size"] == [320, 400] for frame in frames)
    assert payload["evaluation_assumption"] == {"metric": "count_mae", "target": .5, "review_required": True}
    assert before == {name: (harness.root / name).read_bytes() for name in before}
    assert not harness.service.events(harness.project_id) and not (harness.root / "deployment.json").exists()
    assert read_usage(harness.root).uses
    state = harness.store.get(harness.project_id, harness.task_id)
    assert state.stage == "investigating" and state.selected_workflow_revision == payload["workflow_revision_id"]
    assert state.preview_observation_id == observation.id and state.status == "running"
    artifacts = Artifacts(harness.store.root(harness.project_id, harness.task_id))
    revision = json.loads(artifacts.read(payload["revision_artifact"]))
    saved_spec = json.loads(artifacts.read(revision["artifacts"]["spec"]))
    assert saved_spec["inputs"]["source"]["path"].endswith(f"workflows/{revision['id']}/media")
    assert json.loads(artifacts.read(revision["artifacts"]["bindings"])) == payload["model_bindings"]
    assert all(Path(row["preview_path"]).read_bytes() == Path(row["source_path"]).read_bytes() for row in payload["input_refs"])


def test_event_outputs_are_preview_values_without_persisted_effects(harness: Harness) -> None:
    harness.inspect()
    observation = harness.construct(harness.action(graph(events=True)))
    assert observation.status == "completed", observation.error
    assert any(frame["events"] for frame in observation.payload["preview"]["frames"])
    assert not harness.service.events(harness.project_id)
    assert harness.service.get_project(harness.project_id).candidates == []


def test_selected_context_binds_actual_fixture_preview_transforms_and_applied_graph(harness: Harness) -> None:
    from mcp_server.investigations import investigation_context

    harness.inspect()
    observation = harness.construct()
    context = investigation_context(harness.store, harness.project_id, harness.task_id)
    selected = context["selected_workflow"]
    assert selected["preview_observation_id"] == observation.id
    assert selected["spec_hash"] == selected["preview_spec_hash"] == observation.payload["spec_hash"]
    assert selected["preview_media_ids"] == harness.media_ids
    inference = selected["preview"]["frames"][0]["inferences"][0]
    assert inference["input_to_frame"] == [0, 0, .5, 1]
    assert inference["result"]["input_size"] == [320, 400]
    nodes = selected["applied_graph"]["nodes"]
    assert nodes[1]["box"] == [0, 0, .5, 1] and nodes[2]["width"] == 320 and nodes[2]["height"] == 400
    assert selected["applied_graph"]["action_id"] == observation.action_id
    assert not harness.service.events(harness.project_id)


def test_uninspected_capability_cannot_construct_or_execute(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("engine.investigations.workflows.run_pipeline", lambda *_a, **_k: pytest.fail("Uninspected inference"))
    observation = harness.construct()
    assert observation.status == "failed" and "Inspect capability" in observation.error["message"]
    assert not observation.payload["executed"] and "workflow_revision_id" not in observation.payload
    assert harness.store.get(harness.project_id, harness.task_id).selected_workflow_revision is None


def test_inspection_in_another_task_does_not_authorize_current_task(harness: Harness) -> None:
    harness.inspect()
    harness.task_id = harness.store.create(harness.project_id, "Separate investigation").id
    observation = harness.construct()
    assert observation.status == "failed" and "Inspect capability" in observation.error["message"]


def test_stale_descriptor_is_rejected_before_execution(harness: Harness) -> None:
    harness.inspect()
    harness.capability.description += " changed after inspection"
    observation = harness.construct()
    assert observation.status == "failed" and "changed" in observation.error["message"]
    assert not observation.payload["executed"]


def test_current_closed_vocabulary_cannot_be_bypassed(harness: Harness) -> None:
    harness.inspect()
    proposed = graph()
    next(node for node in proposed.nodes if node.type == "detect").classes = ["forklift"]
    observation = harness.construct(harness.action(proposed))
    assert observation.status == "failed" and "does not cover" in observation.error["message"]
    assert not observation.payload["executed"]


def test_workflow_pixel_bound_is_enforced_before_model_execution(harness: Harness) -> None:
    harness.inspect()
    proposed = graph()
    resize = next(node for node in proposed.nodes if node.type == "resize")
    resize.width, resize.height = 8192, 8192
    observation = harness.construct(harness.action(proposed))
    assert observation.status == "failed" and "40 million" in observation.error["message"]
    assert not observation.payload["executed"]


def test_frozen_preview_inputs_remain_exact_after_original_media_changes(harness: Harness) -> None:
    harness.inspect()
    observation = harness.construct()
    assert observation.status == "completed", observation.error
    reference = observation.payload["input_refs"][0]
    frozen = Path(reference["preview_path"])
    before = frozen.read_bytes()
    Path(reference["source_path"]).write_bytes(b"changed after the recorded preview")
    assert not frozen.is_symlink() and frozen.read_bytes() == before
    assert observation.payload["preview"]["frames"][0]["source_image_sha256"] == reference["source_sha256"]


@pytest.mark.parametrize("source", ["reserved", "foreign"])
def test_selected_media_requires_current_project_development_membership(harness: Harness, source: str) -> None:
    harness.inspect()
    action = harness.action()
    if source == "reserved":
        config = read_configuration(harness.root, harness.service.annotations(harness.project_id))
        save_configuration(harness.root, harness.service.annotations(harness.project_id), EvaluationConfigurationUpdate(
            expected_revision=config.revision, assignments=[EvidenceAssignment(image_path=row.image_path, split="acceptance",
                scene_group="reserved", data_origin=row.data_origin) for row in config.images], policy=config.policy))
    else:
        other = harness.service.create_project("Other project").id
        action.media_ids = [media_identifier(other, "media/synthetic-02.png")]
    before = read_usage(harness.root)
    observation = harness.construct(action)
    assert observation.status == "failed" and "development" in observation.error["message"]
    assert not observation.payload["executed"] and read_usage(harness.root) == before


def test_duplicate_acceptance_pixels_cannot_enter_the_frozen_preview_set(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    harness.inspect()
    config = read_configuration(harness.root, harness.service.annotations(harness.project_id))
    reserved = next(row for row in config.images if row.image_path.endswith("synthetic-03.png"))
    save_configuration(harness.root, harness.service.annotations(harness.project_id), EvaluationConfigurationUpdate(
        expected_revision=config.revision, assignments=[EvidenceAssignment(image_path=reserved.image_path,
            split="acceptance", scene_group="reserved", data_origin=reserved.data_origin)], policy=config.policy))
    (harness.root / "media/synthetic-02.png").write_bytes((harness.root / reserved.image_path).read_bytes())
    monkeypatch.setattr("engine.investigations.workflows.run_pipeline", lambda *_a, **_k: pytest.fail("Reserved pixels executed"))
    observation = harness.construct()
    assert observation.status == "failed" and not observation.payload["executed"]
    assert "development" in observation.error["message"] or "reserved" in observation.error["message"]


def test_confirmed_host_zones_are_frozen_and_unconfirmed_geometry_is_rejected(harness: Harness) -> None:
    harness.inspect()
    first = harness.construct(harness.action(graph(zones=True)))
    assert first.status == "completed", first.error
    artifacts = Artifacts(harness.store.root(harness.project_id, harness.task_id))
    revision = json.loads(artifacts.read(first.payload["revision_artifact"]))
    saved = json.loads(artifacts.read(revision["artifacts"]["spec"]))
    zone = next(block for block in saved["blocks"] if block["type"] == "zone_filter")
    assert zone["params"]["zones"].endswith(f"workflows/{revision['id']}/zones.json")
    (harness.root / "synthetic-provenance.json").unlink()
    second = harness.construct(harness.action(graph(zones=True)))
    assert second.status == "failed" and "confirm" in second.error["message"]
    assert harness.store.get(harness.project_id, harness.task_id).selected_workflow_revision == first.payload["workflow_revision_id"]


@pytest.mark.parametrize("stage", ["compilation", "preview"])
def test_compile_and_preview_failures_preserve_diagnostics_without_a_draft(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    harness.inspect()
    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("Deliberate actual boundary failure")
    monkeypatch.setattr("engine.investigations.workflows." + ("compile_pipeline" if stage == "compilation" else "run_pipeline"), fail)
    observation = harness.construct()
    assert observation.status == "failed" and observation.error["failed_stage"] == stage
    assert observation.payload["executed"] is (stage == "preview")
    assert observation.payload["preview_success"] is False and "workflow_revision_id" not in observation.payload
    assert "diagnostic_artifact" in observation.payload and "proposal_artifact" in observation.payload
    assert not list(harness.store.root(harness.project_id, harness.task_id).glob("workflows/*/version.json"))
    assert harness.store.get(harness.project_id, harness.task_id).selected_workflow_revision is None


def test_unreserved_and_closed_actions_do_not_rerun_workflow(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    harness.inspect()
    rejected = construct_workflow(harness.service, harness.store, harness.project_id, harness.task_id, "0" * 32, harness.action())
    assert rejected.status == "failed" and not rejected.payload["executed"]
    completed = harness.construct()
    receipt = next(row for row in harness.store.actions(harness.project_id, harness.task_id) if row.id == completed.action_id)
    monkeypatch.setattr("engine.investigations.workflows.run_pipeline", lambda *_a, **_k: pytest.fail("Closed action reran"))
    rejected = construct_workflow(harness.service, harness.store, harness.project_id, harness.task_id, receipt.id, receipt.action)
    assert rejected.status == "failed" and not rejected.payload["executed"]


def test_successful_parent_is_immutable_and_unknown_parent_is_rejected(harness: Harness) -> None:
    harness.inspect()
    first = harness.construct()
    assert first.status == "completed", first.error
    version_path = harness.store.root(harness.project_id, harness.task_id) / "workflows" / first.payload["workflow_revision_id"] / "version.json"
    before = version_path.read_bytes()
    second = harness.construct(harness.action(parent_revision_id=first.payload["workflow_revision_id"], evidence_ids=[first.id]))
    assert second.status == "completed", second.error
    assert second.payload["workflow_revision_id"] != first.payload["workflow_revision_id"]
    assert version_path.read_bytes() == before
    failed = harness.construct(harness.action(parent_revision_id="f" * 32))
    assert failed.status == "failed" and "Parent revision" in failed.error["message"]


@pytest.mark.parametrize("mutation", ["empty", "model", "source", "missing_branch"])
def test_preview_receipt_must_match_the_actual_bound_sources_and_models(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    from engine.runtime import run_pipeline
    harness.inspect()
    def changed(*args: Any, **kwargs: Any) -> Any:
        result = run_pipeline(*args, **kwargs)
        if mutation == "empty":
            result.frames = []
        elif mutation == "model":
            result.frames[0].inferences[0].result.identity.model_id = "wrong-model"
        elif mutation == "source":
            result.frames[0].source_image_sha256 = "0" * 64
        else:
            result.frames[0].inferences = []
        return result
    monkeypatch.setattr("engine.investigations.workflows.run_pipeline", changed)
    observation = harness.construct()
    assert observation.status == "failed" and observation.payload["preview_success"] is False
    assert "workflow_revision_id" not in observation.payload and observation.payload["executed"] is True
    assert "preview_artifact" in observation.payload
    assert harness.store.get(harness.project_id, harness.task_id).selected_workflow_revision is None
