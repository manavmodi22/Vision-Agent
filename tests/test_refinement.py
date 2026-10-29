"""Plain-language refinements preserve the actual authored graph and human labels."""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.refinement import parse_refinement
from agent.templates import build_template
from engine.builds.refinement import refine_app
from engine.datasets import DatasetConflict, DatasetService
from engine.eval import spec_hash
from engine.service import WorkspaceService
from spec.models import BlockSpec, PipelineSpec
from spec.refinement import RefinementPatch


def authored_app(root: Path) -> tuple[WorkspaceService, str, PipelineSpec]:
    service = WorkspaceService(root)
    project = service.create_project("Keep my authored workflow", "custom")
    service.demo(project.id)
    spec = build_template("pallets", "media", "fixture-color-v1")[0]
    spec.name = "Hand-edited lane app"
    spec.eval.target = .7
    detector = next(block for block in spec.blocks if block.type == "detect")
    source = detector.inputs["image"]
    spec.blocks.insert(1, BlockSpec(id="manual_resize", type="resize", params={"width": 640, "height": 400}, inputs={"image": source}))
    detector.inputs["image"] = "$manual_resize.image"
    for block in spec.blocks:
        if block.type == "rule":
            block.params.update({"when": "count >= 7", "hold_s": 30})
        if block.type == "sink_event":
            block.params["alert"] = "warehouse-alert"
    labels = service.annotations(project.id)
    labels.annotations[1].reviewed = False
    service.save_annotations(project.id, labels)
    service.save_candidates(project.id, [spec], "Count pallets by lane with the authored duration rule")
    return service, project.id, spec


@pytest.mark.parametrize("prompt,value", [("raise confidence to0.5", .5), ("Set confidence to 50%", .5),
                                         ("confidence .35", .35), ("Lower the confidence threshold to 0.2.", .2)])
def test_explicit_confidence_parsing(prompt: str, value: float) -> None:
    candidates = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])
    patch = parse_refinement(prompt, candidates)
    assert patch == RefinementPatch(kind="confidence", confidence=value)
    assert parse_refinement(prompt, []) is None


def test_class_parser_is_additive_and_does_not_swallow_spatial_conditions() -> None:
    candidates = build_template("custom", "media", "fixture-color-v1", classes=["person"])
    assert parse_refinement("also count forklifts", candidates) == RefinementPatch(kind="add_classes", classes=["forklift"])
    assert parse_refinement("add class forklift", candidates) == RefinementPatch(kind="add_classes", classes=["forklift"])
    assert parse_refinement("add classes forklifts and cartons", candidates) == RefinementPatch(kind="add_classes", classes=["forklift", "carton"])
    assert parse_refinement("also detect people and cartons", candidates) == RefinementPatch(kind="add_classes", classes=["person", "carton"])
    assert parse_refinement("also count forklifts in zone A", candidates) is None
    with pytest.raises(ValidationError):
        parse_refinement("set confidence to 5", candidates)


def test_confidence_refinement_preserves_all_unrelated_graph_fields_and_annotations(tmp_path: Path) -> None:
    service, project_id, original = authored_app(tmp_path)
    root = service.root(project_id)
    labels_before = (root / "annotations.json").read_bytes()
    classes_before = DatasetService(service).manifest(project_id).classes
    expected = original.model_copy(deep=True)
    for block in expected.blocks:
        if block.type == "detect":
            block.params["min_conf"] = .5
    before_hash = spec_hash(original, root)
    result = refine_app(service, project_id, RefinementPatch(kind="confidence", confidence=.5))
    assert service.candidate(project_id, 0) == expected
    assert (root / "annotations.json").read_bytes() == labels_before
    assert DatasetService(service).manifest(project_id).classes == classes_before
    assert result.preview.frames and len(result.preview.frames) == 5 and result.preview.frames[0].detections
    assert result.base_spec_hash == before_hash and result.spec_hash == spec_hash(expected, root)
    assert result.spec_hash != result.base_spec_hash and not result.requires_review
    assert not service.events(project_id) and service.get_project(project_id).deployment_id is None


def test_class_addition_extends_ontology_preserves_boxes_and_requires_fresh_review(tmp_path: Path) -> None:
    service, project_id, original = authored_app(tmp_path)
    datasets = DatasetService(service)
    old_classes = datasets.manifest(project_id).classes
    labels_before = service.annotations(project_id)
    result = refine_app(service, project_id, RefinementPatch(kind="add_classes", classes=["carton"]))
    expected = original.model_copy(deep=True)
    next(block for block in expected.blocks if block.type == "detect").params["classes"] = ["pallet", "carton"]
    assert service.candidate(project_id, 0) == expected and result.requires_review
    for annotation in labels_before.annotations:
        annotation.reviewed = False
    assert service.annotations(project_id) == labels_before
    with pytest.raises(ValueError, match="reviewed evaluation split"):
        service.evaluate(project_id)
    actual_classes = datasets.manifest(project_id).classes
    assert actual_classes[:len(old_classes)] == old_classes
    assert actual_classes[-1].name == "carton" and actual_classes[-1].id not in {row.id for row in old_classes}
    assert len(result.preview.frames) == 5


@pytest.mark.parametrize("change", ["annotations", "graph", "zones"])
def test_edits_during_refinement_preview_cannot_be_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    import engine.builds.refinement as module
    service, project_id, original = authored_app(tmp_path)
    execute = module.run_pipeline
    edited_labels = None
    def concurrent(*args: object, **kwargs: object) -> object:
        nonlocal edited_labels
        result = execute(*args, **kwargs)
        if change == "annotations":
            edited_labels = service.annotations(project_id)
            edited_labels.annotations[0].detections.pop()
            service.save_annotations(project_id, edited_labels)
        elif change == "graph":
            changed = service.candidate(project_id, 0).model_copy(deep=True)
            changed.name = "Concurrent human edit"
            service.update_candidate(project_id, 0, changed, original)
        else:
            path = service.root(project_id) / "zones" / "lanes.json"
            path.write_text(path.read_text() + "\n")
        return result
    monkeypatch.setattr(module, "run_pipeline", concurrent)
    with pytest.raises(DatasetConflict, match="changed during refinement"):
        refine_app(service, project_id, RefinementPatch(kind="confidence", confidence=.5))
    actual = service.candidate(project_id, 0)
    assert next(block for block in actual.blocks if block.type == "detect").params["min_conf"] != .5
    if edited_labels is not None:
        assert service.annotations(project_id) == edited_labels


def test_failed_preview_never_commits_a_patch_or_new_ontology_class(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.builds.refinement as module
    service, project_id, original = authored_app(tmp_path)
    classes = DatasetService(service).manifest(project_id).classes
    def failed(*args: object, **kwargs: object) -> object:
        raise ValueError("Detector unavailable during real preview")
    monkeypatch.setattr(module, "run_pipeline", failed)
    with pytest.raises(ValueError, match="unavailable"):
        refine_app(service, project_id, RefinementPatch(kind="add_classes", classes=["carton"]))
    assert service.candidate(project_id, 0) == original
    assert DatasetService(service).manifest(project_id).classes == classes
