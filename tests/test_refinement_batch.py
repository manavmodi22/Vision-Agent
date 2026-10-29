"""Real fixture previews establish atomic multi-candidate refinement behavior."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.templates import build_template
from engine.builds.refinement import refine_app
from engine.datasets import DatasetConflict, DatasetService
from engine.service import WorkspaceService
from spec.models import BlockSpec, PipelineSpec
from spec.refinement import RefinementBatch, RefinementPatch


def workspace(tmp_path: Path, *, candidates: int = 2) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Refine fixture", "custom")
    service.demo(project.id)
    first = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    second = first.model_copy(deep=True)
    second.name = "Alternative"
    second.blocks[0].params["fps"] = 4
    next(block for block in second.blocks if block.type == "detect").params["min_conf"] = .4
    service.save_candidates(project.id, [first, second][:candidates], "Count pallets")
    DatasetService(service).manifest(project.id)
    return service, project.id


def detector(spec: PipelineSpec) -> BlockSpec:
    return next(block for block in spec.blocks if block.type == "detect")


def test_composed_goal_changes_preview_every_candidate_and_preserve_other_fields(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path)
    before = service.get_project(project_id)
    labels = service.annotations(project_id)
    result = refine_app(service, project_id, RefinementBatch(patches=[
        RefinementPatch(kind="add_classes", classes=["carton"]),
        RefinementPatch(kind="confidence", confidence=.5),
        RefinementPatch(kind="sample_fps", fps=3),
        RefinementPatch(kind="eval_target", eval_metric="recall", eval_target=.9),
        RefinementPatch(kind="count_rule", count_threshold=5, hold_s=30),
    ]), candidate_index=1)
    assert result.affected_candidate_indices == result.previewed_candidate_indices == [0, 1]
    assert len(result.preview.frames) == 5 and result.requires_review
    assert len(result.spec_hashes) == len(result.base_spec_hashes) == 2
    assert any("duration" in warning for warning in result.preview.warnings)
    changed = service.get_project(project_id)
    assert [spec.name for spec in changed.candidates] == [spec.name for spec in before.candidates]
    assert detector(changed.candidates[0]).params["min_conf"] == detector(before.candidates[0]).params["min_conf"]
    assert detector(changed.candidates[1]).params["min_conf"] == .5
    for candidate in changed.candidates:
        assert detector(candidate).params["classes"] == ["pallet", "carton"]
        assert candidate.blocks[0].params["fps"] == 3
        assert candidate.eval.metric == "recall" and candidate.eval.target == .9
        rule = next(block for block in candidate.blocks if block.type == "rule")
        assert rule.params == {"when": "count >= 5.0", "hold_s": 30.0}
        assert next(block for block in candidate.blocks if block.type == "sink_event").inputs["event"] == f"${rule.id}.event"
    assert [row.detections for row in service.annotations(project_id).annotations] == [row.detections for row in labels.annotations]
    assert not any(row.reviewed for row in service.annotations(project_id).annotations)
    assert not changed.evaluations and changed.deployment_id is None and not service.events(project_id)


def test_class_removal_and_replacement_never_delete_original_labels_or_class_ids(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path)
    refine_app(service, project_id, RefinementPatch(kind="add_classes", classes=["carton"]))
    labels = service.annotations(project_id)
    for row in labels.annotations:
        row.reviewed = True
    service.save_annotations(project_id, labels)
    original_classes = DatasetService(service).manifest(project_id).classes
    original_bytes = (service.root(project_id) / "annotations.json").read_bytes()
    result = refine_app(service, project_id, RefinementBatch(patches=[
        RefinementPatch(kind="remove_classes", classes=["pallet"]),
        RefinementPatch(kind="replace_classes", classes=["carton"]),
    ]))
    assert not result.requires_review
    assert all(detector(spec).params["classes"] == ["carton"] for spec in service.get_project(project_id).candidates)
    assert (service.root(project_id) / "annotations.json").read_bytes() == original_bytes
    assert DatasetService(service).manifest(project_id).classes == original_classes


def test_final_batch_coverage_not_intermediate_edits_controls_review(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path, candidates=1)
    before = service.annotations(project_id)
    result = refine_app(service, project_id, RefinementBatch(patches=[
        RefinementPatch(kind="remove_classes", classes=["pallet"]),
        RefinementPatch(kind="add_classes", classes=["pallet"]),
    ]))
    assert not result.requires_review and service.annotations(project_id) == before


@pytest.mark.parametrize("failure", ["second_preview", "write"])
def test_any_failure_keeps_all_candidate_labels_ontology_and_approvals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    import engine.builds.refinement as execution
    import engine.builds.refinement_commit as commit
    service, project_id = workspace(tmp_path)
    root = service.root(project_id)
    # Deliberate test sentinel, never an approval in a real project.
    (root / "deployment.json").write_text('{"test_sentinel":true}')
    originals = {name: (root / name).read_bytes() for name in
                 ("project.json", "annotations.json", "dataset-metadata.json", "deployment.json")}
    if failure == "second_preview":
        run = execution.run_pipeline
        count = 0
        def failed(*args: object, **kwargs: object) -> object:
            nonlocal count
            count += 1
            if count == 2:
                raise ValueError("second candidate preview failed")
            return run(*args, **kwargs)
        monkeypatch.setattr(execution, "run_pipeline", failed)
    else:
        save = commit.atomic_model
        def failed_write(path: Path, value: object) -> None:
            if path.name == "project.json":
                raise ValueError("injected project write failure")
            save(path, value)
        monkeypatch.setattr(commit, "atomic_model", failed_write)
    with pytest.raises(ValueError):
        refine_app(service, project_id, RefinementPatch(kind="add_classes", classes=["carton"]))
    assert {name: (root / name).read_bytes() for name in originals} == originals


@pytest.mark.parametrize("mutation", ["alternate", "holdout", "pixels"])
def test_stale_other_candidate_holdout_and_pixels_abort_entire_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    from PIL import Image

    import engine.builds.refinement as module
    service, project_id = workspace(tmp_path)
    run = module.run_pipeline
    def concurrent(*args: object, **kwargs: object) -> object:
        result = run(*args, **kwargs)
        if mutation == "alternate":
            original = service.candidate(project_id, 1)
            changed = original.model_copy(update={"name": "Human changed alternative"}, deep=True)
            service.update_candidate(project_id, 1, changed, original)
        elif mutation == "holdout":
            (service.root(project_id) / "active-holdout.json").write_text(service.annotations(project_id).model_dump_json())
        else:
            path = service.get_project(project_id).media[0]
            with Image.open(path) as image:
                image.putpixel((0, 0), (19, 30, 40))
                image.save(path)
        return result
    monkeypatch.setattr(module, "run_pipeline", concurrent)
    with pytest.raises(DatasetConflict, match="changed during refinement"):
        refine_app(service, project_id, RefinementPatch(kind="confidence", confidence=.6))
    assert detector(service.candidate(project_id, 0)).params["min_conf"] != .6


def test_ambiguous_rule_insertion_does_not_guess_a_count_branch(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path, candidates=1)
    spec = service.candidate(project_id, 0)
    spec.blocks = [block for block in spec.blocks if block.type not in {"rule", "sink_event"}]
    count = next(block for block in spec.blocks if block.type == "count_per_zone")
    spec.blocks.append(count.model_copy(update={"id": "other_count"}, deep=True))
    service.save_candidates(project_id, [spec], "Count")
    with pytest.raises(ValueError, match="ambiguous"):
        refine_app(service, project_id, RefinementPatch(kind="count_rule", count_threshold=5))
    assert service.candidate(project_id, 0) == spec


def test_expected_text_inserts_match_and_sink_after_unique_reader() -> None:
    from engine.builds.refinement_edits import apply_edit
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    candidate.blocks = [block for block in candidate.blocks if block.type not in {"match", "sink_event"}]
    before = candidate.model_copy(deep=True)
    apply_edit(candidate, RefinementPatch(kind="expected_text", expected_text="SKU-002"), {})
    assert candidate.blocks[:len(before.blocks)] == before.blocks
    match = next(block for block in candidate.blocks if block.type == "match")
    assert match.params == {"expected": "SKU-002", "mode": "exact"}
    assert next(block for block in candidate.blocks if block.type == "sink_event").inputs["event"] == f"${match.id}.event"
    apply_edit(candidate, RefinementPatch(kind="expected_text", expected_text="SKU-003", match_mode="contains"), {})
    assert match.params == {"expected": "SKU-003", "mode": "contains"}
    assert len(candidate.blocks) == len(before.blocks) + 2


@pytest.mark.parametrize("value", [
    {"kind": "count_rule", "confidence": .4}, {"kind": "eval_target", "eval_metric": "recall", "eval_target": 90},
    {"kind": "sample_fps", "fps": 0}, {"kind": "replace_classes", "classes": []},
    {"kind": "expected_text", "match_mode": "exact"}, {"kind": "confidence", "confidence": float("nan")},
])
def test_invalid_contract_rejects_without_execution(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RefinementPatch.model_validate(value)


def test_count_only_app_gains_real_rule_events_without_changing_existing_blocks(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path, candidates=1)
    spec = build_template("pallets", "media", "fixture-color-v1")[0]
    spec.blocks = [block for block in spec.blocks if block.type not in {"rule", "sink_event"}]
    service.save_candidates(project_id, [spec], "Count pallets in the saved lanes")
    result = refine_app(service, project_id, RefinementPatch(kind="count_rule", count_threshold=3))
    actual = service.candidate(project_id, 0)
    assert actual.blocks[:len(spec.blocks)] == spec.blocks
    assert [block.type for block in actual.blocks[len(spec.blocks):]] == ["rule", "sink_event"]
    assert any(frame.events for frame in result.preview.frames)
    assert not service.events(project_id), "Preview events are hypotheses, not persisted monitoring events"
    assert not result.requires_review


def test_empty_detector_class_set_and_invalid_metric_reject_whole_batch(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path)
    before = service.get_project(project_id)
    for patches in [
        [RefinementPatch(kind="remove_classes", classes=["pallet"])],
        [RefinementPatch(kind="sample_fps", fps=5), RefinementPatch(kind="eval_target", eval_metric="text_accuracy")],
    ]:
        with pytest.raises(ValueError):
            refine_app(service, project_id, RefinementBatch(patches=patches))
        assert service.get_project(project_id) == before


@pytest.mark.parametrize("change", [False, True])
def test_real_change_revokes_gate_but_noop_preview_preserves_it(tmp_path: Path, change: bool) -> None:
    service, project_id = workspace(tmp_path, candidates=1)
    assert service.evaluate(project_id).passed
    # Isolated generated-fixture approval, never a user project.
    service.deploy(project_id, 0, approved=True)
    root = service.root(project_id)
    before = {name: (root / name).read_bytes() for name in ("project.json", "deployment.json", "eval-media.json")}
    refine_app(service, project_id, RefinementPatch(kind="confidence", confidence=.5 if change else .4))
    if change:
        assert not (root / "deployment.json").exists() and not (root / "eval-media.json").exists()
        assert service.get_project(project_id).evaluations == []
        with pytest.raises(ValueError, match="Approve deployment"):
            service.run(project_id)
    else:
        assert {name: (root / name).read_bytes() for name in before} == before


async def test_multi_change_batch_roundtrips_through_captured_mcp_tool(tmp_path: Path) -> None:
    from agent.machine import AgentState
    from agent.mcp_client import connect_tools
    from agent.refinement_contracts import RefinementDecision
    from engine.builds.store import BuildStore
    from spec.refinement import RefinementResult
    service, project_id = workspace(tmp_path)
    store = BuildStore(service)
    record = store.create(project_id, "Use at least five pallets for ten seconds, sample at three FPS, and require 90% recall")
    batch = RefinementBatch(patches=[
        RefinementPatch(kind="count_rule", count_threshold=5, hold_s=10),
        RefinementPatch(kind="sample_fps", fps=3),
        RefinementPatch(kind="eval_target", eval_metric="recall", eval_target=.9),
    ])
    decision = RefinementDecision(message="Deterministic test interpretation; no real language-model claim",
                                  questions=[], patches=batch.patches)
    language_call = store.start_model_call(project_id, record.view.id, "deterministic-test-refinement",
                                          {"prompt": record.prompt, "test_stub": True})
    store.finish_call(project_id, record.view.id, language_call.id,
                      {"decision": decision.model_dump(mode="json")})
    store.record_refinement_decision(project_id, record.view.id, decision.model_dump(mode="json"))
    async with connect_tools(str(service.repository.root), AgentState()) as tools:
        await tools.bind_build(project_id, record.view.id)
        result = RefinementResult.model_validate(await tools.call("build_refine", {
            "project_id": project_id, "build_id": record.view.id,
            "candidate_index": 1, "batch": batch.model_dump(mode="json"),
        }))
    assert result.previewed_candidate_indices == [0, 1]
    assert result.preview.frames and result.preview.frames[0].detections
    actual = service.get_project(project_id)
    for candidate in actual.candidates:
        assert candidate.eval.metric == "recall" and candidate.eval.target == .9
        assert next(block for block in candidate.blocks if block.type == "rule").params["hold_s"] == 10
    current = store.get(project_id)
    store.assert_current(current)
    assert len(current.operation.calls) == 2
    captured = current.operation.calls[-1]
    assert captured.name == "build_refine" and captured.status == "completed" and captured.result
    assert captured.result["previewed_candidate_indices"] == [0, 1]
    assert actual.deployment_id is None and not actual.evaluations and not service.events(project_id)


async def test_broad_followup_build_previews_and_evaluates_all_changed_alternatives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    import engine.builds.manager as module
    from agent.refinement_contracts import RefinementDecision
    from engine.builds.store import BuildStore
    service, project_id = workspace(tmp_path)
    originals = service.get_project(project_id).candidates
    detector(originals[0]).params["min_conf"] = 1.0
    service.save_candidates(project_id, originals, "Count pallets")
    labels = service.annotations(project_id)
    requests = []
    async def interpreted(prompt: str, settings: object, build_id: str, candidate_index: int = 0) -> RefinementDecision:
        requests.append(prompt)
        decision = RefinementDecision(message="Deterministic language stub for actual batch execution", questions=[], patches=[
            RefinementPatch(kind="count_rule", count_threshold=3, hold_s=0),
            RefinementPatch(kind="sample_fps", fps=3),
            RefinementPatch(kind="eval_target", eval_metric="recall", eval_target=.95),
        ])
        store = BuildStore(service)
        call = store.start_model_call(project_id, build_id, "deterministic-test-refinement", {"prompt": prompt, "test_stub": True})
        store.finish_call(project_id, build_id, call.id, {"decision": decision.model_dump(mode="json")})
        store.record_refinement_decision(project_id, build_id, decision.model_dump(mode="json"))
        return decision
    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("An existing application must not be rebuilt from a template")
    monkeypatch.setattr(module, "interpret_refinement", interpreted)
    monkeypatch.setattr(module, "agent_plan", forbidden)
    manager = module.BuildManager(service)
    try:
        await manager.start(project_id, "Flag at least three pallets, sample at three frames per second, and require 95% recall")
        await asyncio.wait_for(manager.tasks[project_id], timeout=40)
        status = manager.status(project_id)
        assert status.status == "awaiting_approval" and status.selected_candidate_index == 1, status
        assert len(requests) == 1 and status.preview and status.preview.frames[0].detections
        assert len(status.evaluations) == 2 and not status.evaluations[0].passed and status.evaluations[1].passed
        project = service.get_project(project_id)
        assert service.annotations(project_id) == labels
        assert [candidate.name for candidate in project.candidates] == [candidate.name for candidate in originals]
        assert [detector(candidate).params["min_conf"] for candidate in project.candidates] == [1.0, .4]
        calls = manager.store.get(project_id).operation.calls
        captured = next(call for call in calls if call.name == "build_refine")
        assert captured.result and captured.result["previewed_candidate_indices"] == [0, 1]
        assert len([call for call in calls if call.name == "eval_run"]) == 2
        assert project.deployment_id is None and not service.events(project_id)
    finally:
        await manager.close()


def test_hold_change_with_repeated_comparison_preserves_original_expression(tmp_path: Path) -> None:
    service, project_id = workspace(tmp_path, candidates=1)
    original = service.candidate(project_id, 0)
    rule = next(block for block in original.blocks if block.type == "rule")
    rule.params["when"] = "count >= 3"
    service.save_candidates(project_id, [original], "Count pallets")
    expected = original.model_copy(deep=True)
    next(block for block in expected.blocks if block.type == "rule").params["hold_s"] = 90.0
    refine_app(service, project_id, RefinementPatch(kind="count_rule", count_threshold=3.0,
                                                 count_operator=">=", hold_s=90))
    assert service.candidate(project_id, 0) == expected
