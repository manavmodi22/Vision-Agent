"""Safe typed edits retain immutable per-block capability evidence across builds."""
import json
from pathlib import Path

import pytest

from agent.graph_authoring import compose_graph, graph_model_selections
from agent.machine import AgentConflict, Phase
from engine.builds.store import BuildStore
from engine.platform.planning_options import options_digest, planning_options
from engine.platform.store import digest
from engine.service import WorkspaceService
from spec.authoring import GraphCandidate
from spec.planning import PlanningOptions
from spec.platform import BuildPlan


def fixture(tmp_path: Path, count: int = 1, *, captured: bool = True,
            publish: bool = True) -> tuple[BuildStore, str, BuildPlan | None, PlanningOptions]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Refinement binding software fixture", "custom")
    service.demo(project.id)
    options = planning_options(service, project.id, "fixture-color-v1")
    graph = GraphCandidate.model_validate({"name": "Captured graph 0.2 detector", "nodes": [
        {"type": "frame_sample", "id": "sample", "fps": 2},
        {"type": "detect", "id": "det", "image": "$sample.frame", "classes": ["pallet"],
         "min_confidence": .4, "model_capability_id": "model.fixture-color-v1",
         "model_reason": "Synthetic software test; no model quality claim"}],
        "metric": "recall", "target": .9})
    graphs = [graph.model_copy(deep=True) for _ in range(count)]
    candidates = [compose_graph(value, "media", options) for value in graphs]
    service.save_candidates(project.id, candidates, "Detect pallets")
    store = BuildStore(service)
    original = None
    if publish:
        original, _ = store.platform.publish(project.id, "a" * 32, "Detect pallets", candidates,
            Phase.COMPILE, "Original typed proposal",
            planning_options=options if captured else None,
            model_selections=graph_model_selections(graphs, options) if captured else None)
    return store, project.id, original, options


def start_refinement(store: BuildStore, project_id: str, patch: dict[str, object]) -> BuildPlan:
    record = store.create(project_id, "Apply the requested safe edit")
    request = {"project_id": project_id, "patch": patch}
    call = store.start_call(project_id, record.view.id, "build_refine", request)
    assert call.status == "running"
    plan = store.platform.plans(project_id)[-1]
    assert plan.build_id == record.view.id
    return plan


@pytest.mark.parametrize("patch", [
    {"kind": "confidence", "confidence": .55},
    {"kind": "crop", "block_id": "det", "crop_box": [0, 0, .5, 1]},
])
def test_actual_build_refinement_keeps_exact_graph_bindings_across_builds(
    tmp_path: Path, patch: dict[str, object],
) -> None:
    store, project_id, original, options = fixture(tmp_path, 2)
    assert original is not None and original.build_id is None
    plan = start_refinement(store, project_id, patch)
    assert plan.candidates != original.candidates
    assert plan.model_selections == original.model_selections
    assert plan.planning_options_artifact_id
    assert store.platform.artifact_content(project_id, plan.planning_options_artifact_id).content == options.model_dump(mode="json")
    assert store.platform.plan(project_id, original.id) == original
    assert len(store.get(project_id).operation.calls) == 1
    changed = plan.candidates[0]
    if patch["kind"] == "confidence":
        assert next(block.params["min_conf"] for block in changed.blocks if block.id == "det") == .55
        assert plan.candidates[1] == original.candidates[1]
    else:
        crop = next(block for block in changed.blocks if block.type == "crop")
        assert crop.params["box"] == [0, 0, .5, 1]
        assert next(block.inputs["image"] for block in changed.blocks if block.id == "det") == f"${crop.id}.image"


def test_origin_is_the_matching_pre_edit_graph_not_the_latest_proposal(tmp_path: Path) -> None:
    store, project_id, original, options = fixture(tmp_path)
    assert original is not None
    different = original.candidates[0].model_copy(deep=True)
    different.blocks[1].params["min_conf"] = .8
    unrelated, _ = store.platform.publish(project_id, "b" * 32, "Another proposal", [different],
        Phase.COMPILE, "Not saved as the project graph", planning_options=options,
        model_selections=[item.model_copy(update={"proposed_reason": "A distinct, unrelated proposal"})
                          for item in original.model_selections])
    plan = start_refinement(store, project_id, {"kind": "confidence", "confidence": .55})
    assert plan.parent_plan_id == unrelated.id  # Revision lineage is independent of model-evidence origin.
    assert plan.model_selections == original.model_selections
    assert plan.planning_options_artifact_id


@pytest.mark.parametrize("mutation", ["model", "add", "remove", "rename", "type", "duplicate", "source"])
def test_changed_inference_identity_is_rejected_before_a_build_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    store, project_id, original, _ = fixture(tmp_path)
    assert original is not None
    proposed = original.candidates[0].model_copy(deep=True)
    block = proposed.blocks[1]
    if mutation == "model":
        block.params["model"] = "unrecorded-detector"
    elif mutation in {"add", "duplicate"}:
        extra = block.model_copy(deep=True)
        extra.id = "second" if mutation == "add" else block.id
        proposed.blocks.append(extra)
    elif mutation == "remove":
        proposed.blocks.remove(block)
    elif mutation == "rename":
        block.id = "renamed"
    elif mutation == "type":
        block.type = "detect_open_vocab"
    else:
        proposed.inputs["source"].path = "other-media"
    monkeypatch.setattr("engine.platform.proposals.refinement_candidates", lambda *_: [proposed])
    record = store.create(project_id, "Set confidence to 0.55")
    with pytest.raises(ValueError, match="inference identity|duplicate block"):
        store.start_call(project_id, record.view.id, "build_refine",
            {"project_id": project_id, "patch": {"kind": "confidence", "confidence": .55}})
    assert store.platform.plans(project_id) == [original]
    assert not store.get(project_id).operation.calls


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "mixed", "snapshot", "no_options"])
def test_incomplete_origin_bindings_cannot_become_a_legacy_refinement(tmp_path: Path, mutation: str) -> None:
    store, project_id, original, _ = fixture(tmp_path, 2)
    assert original is not None
    raw = original.model_dump(mode="json", by_alias=True)
    if mutation == "missing":
        raw["model_selections"] = []
    elif mutation == "duplicate":
        raw["model_selections"][1] = raw["model_selections"][0].copy()
    elif mutation == "mixed":
        raw["model_selections"][1]["block_id"] = None
    elif mutation == "snapshot":
        raw["model_selections"][1]["options_snapshot_id"] = "wrong-snapshot"
    else:
        raw["planning_options_artifact_id"] = None
    # Exercise semantic validation independently of the already-covered immutable hash check.
    raw["content_hash"] = digest({key: value for key, value in raw.items() if key != "content_hash"})
    store.platform.path(project_id, "plans", original.id).write_text(json.dumps(raw))
    with pytest.raises((ValueError, AgentConflict), match="captured model evidence|bindings|captured model capability"):
        start_refinement(store, project_id, {"kind": "confidence", "confidence": .55})
    assert len(store.platform.plans(project_id)) == 1
    assert not store.get(project_id).operation.calls


def test_refinement_rechecks_closed_vocabulary_before_publishing(tmp_path: Path) -> None:
    store, project_id, original, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="does not cover.*forklift"):
        start_refinement(store, project_id, {"kind": "add_classes", "classes": ["forklift"]})
    assert store.platform.plans(project_id) == [original]
    assert not store.get(project_id).operation.calls


def test_supported_class_edit_keeps_the_same_model_receipt(tmp_path: Path) -> None:
    store, project_id, original, _ = fixture(tmp_path)
    assert original is not None
    plan = start_refinement(store, project_id, {"kind": "add_classes", "classes": ["carton"]})
    assert plan.model_selections == original.model_selections
    assert next(block.params["classes"] for block in plan.candidates[0].blocks if block.id == "det") == ["pallet", "carton"]


def test_stale_capability_rejects_edit_without_superseding_current_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, project_id, original, options = fixture(tmp_path)
    assert original is not None
    record = store.create(project_id, "Set confidence to 0.55")
    same, execution = store.platform.publish(project_id, record.view.id, record.prompt, original.candidates,
        Phase.PLAN, "Existing build authority", build_id=record.view.id,
        planning_options=options, model_selections=original.model_selections)
    changed = options.model_copy(deep=True)
    next(item for item in changed.eligible_models if item.model_id == "fixture-color-v1").version = "changed-version"
    changed.snapshot_id = options_digest(changed)
    monkeypatch.setattr("engine.platform.planning_options._project_options", lambda *_: changed)
    with pytest.raises(ValueError, match="changed or became unavailable"):
        store.start_call(project_id, record.view.id, "build_refine",
            {"project_id": project_id, "patch": {"kind": "confidence", "confidence": .55}})
    assert store.platform.plans(project_id) == [original, same]
    assert store.platform.execution(project_id, record.view.id) == execution
    assert not store.get(project_id).operation.calls


def test_unrecorded_project_graph_cannot_inherit_an_unrelated_plan(tmp_path: Path) -> None:
    store, project_id, original, _ = fixture(tmp_path)
    assert original is not None
    changed = original.candidates[0].model_copy(deep=True)
    changed.blocks[1].params["min_conf"] = .6
    store.service.save_candidates(project_id, [changed], "Changed outside the saved plan")
    with pytest.raises(AgentConflict, match="No immutable model plan matches"):
        start_refinement(store, project_id, {"kind": "confidence", "confidence": .55})
    assert store.platform.plans(project_id) == [original]


@pytest.mark.parametrize("published", [False, True])
def test_genuine_legacy_graphs_still_refine_without_invented_bindings(tmp_path: Path, published: bool) -> None:
    store, project_id, _, _ = fixture(tmp_path, captured=False, publish=published)
    plan = start_refinement(store, project_id, {"kind": "confidence", "confidence": .55})
    assert plan.model_selections == [] and plan.planning_options_artifact_id is None


def test_unchanged_next_phase_retains_composed_bindings(tmp_path: Path) -> None:
    store, project_id, original, _ = fixture(tmp_path)
    assert original is not None
    plan, _ = store.platform.publish(project_id, "b" * 32, "Evaluate", original.candidates,
        Phase.EVALUATE, "Next authorized phase")
    assert plan.model_selections == original.model_selections
    assert plan.planning_options_artifact_id


def test_legacy_single_model_receipt_is_preserved_without_rewriting_its_shape(tmp_path: Path) -> None:
    store, project_id, original, options = fixture(tmp_path)
    assert original is not None
    bindings = [item.model_copy(update={"block_id": None}) for item in original.model_selections]
    legacy, _ = store.platform.publish(project_id, "b" * 32, "Historical selected detector", original.candidates,
        Phase.COMPILE, "Legacy one-model selection", planning_options=options, model_selections=bindings)
    plan = start_refinement(store, project_id, {"kind": "confidence", "confidence": .55})
    assert plan.model_selections == legacy.model_selections and plan.model_selections[0].block_id is None
