"""Explicit structural edits are branch-local and preview actual transformed pixels."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
from agent.refinement_output import RefinementModelDecision
from agent.templates import build_template
from engine.builds.preprocessing_edits import apply_preprocessing
from engine.builds.refinement import refine_app
from engine.datasets import DatasetConflict, DatasetService
from engine.service import WorkspaceService
from spec.models import BlockSpec, PipelineSpec
from spec.preprocessing import preprocessing_target
from spec.refinement import RefinementBatch, RefinementContext, RefinementPatch


def block(identifier: str, kind: str, image: str, **params: object) -> BlockSpec:
    return BlockSpec.model_validate({"id": identifier, "type": kind, "in": {"image": image}, "params": params})


def app() -> PipelineSpec:
    return build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]


def context(candidate: PipelineSpec) -> RefinementContext:
    return RefinementContext(candidates=[candidate], selected_candidate_index=0,
        current_goal="Detect pallets", conversation=[], classes=["pallet"], saved_zone_ids=[], clarification_count=0)


def validate(prompt: str, patches: list[RefinementPatch], candidate: PipelineSpec | None = None) -> None:
    validate_refinement_intent(RefinementDecision(message="Typed test proposal, not language quality evidence",
        questions=[], patches=patches), prompt, context(candidate or app()))


@pytest.mark.parametrize("value", [
    {"kind": "crop"}, {"kind": "crop", "crop_box": [0, 0, 0, 1]},
    {"kind": "crop", "crop_box": [-.1, 0, .5, 1]},
    {"kind": "crop", "crop_box": [0, 0, float("nan"), 1]},
    {"kind": "crop", "crop_box": [0, 0, 1, float("inf")]},
    {"kind": "crop", "crop_box": [0, 0, .5]},
    {"kind": "crop", "crop_box": [0, 0, .5, 1], "width": 100},
    {"kind": "resize", "width": 640}, {"kind": "resize", "width": True, "height": 480},
    {"kind": "resize", "width": 1.5, "height": 480},
    {"kind": "resize", "width": 8193, "height": 480},
    {"kind": "resize", "width": 640, "height": 0},
])
def test_patch_requires_valid_explicit_geometry(value: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RefinementPatch.model_validate(value)


def test_model_output_normalizes_new_discriminated_variants() -> None:
    result = RefinementModelDecision.model_validate({"message": "Crop then resize", "questions": [], "patches": [
        {"kind": "crop", "crop_box": [0, 0, .5, 1], "block_id": "det"},
        {"kind": "resize", "width": 320, "height": 200, "block_id": "det"}]}).normalized()
    assert [patch.kind for patch in result.patches] == ["crop", "resize"]
    assert all(patch.target_scope() == "all" for patch in result.patches)
    with pytest.raises(ValidationError):
        RefinementModelDecision.model_validate({"message": "Invalid", "questions": [], "patches": [
            {"kind": "resize", "width": 320, "height": 200, "crop_box": [0, 0, .5, 1]}]})


def test_insertion_and_existing_transform_update_preserve_inference_and_outputs() -> None:
    candidate = app()
    before = candidate.model_copy(deep=True)
    apply_preprocessing(candidate, RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1]))
    apply_preprocessing(candidate, RefinementPatch(kind="resize", width=320, height=200))
    apply_preprocessing(candidate, RefinementPatch(kind="crop", crop_box=[.5, 0, 1, 1]))
    nodes = {node.id: node for node in candidate.blocks}
    assert nodes["det"].inputs == {"image": "$refined_resize.image"}
    assert nodes["refined_resize"].inputs == {"image": "$refined_crop.image"}
    assert nodes["refined_crop"].params == {"box": [.5, 0, 1, 1]}
    assert len(candidate.blocks) == len(before.blocks) + 2
    for original in before.blocks:
        assert nodes[original.id].params == original.params
        if original.id != "det":
            assert nodes[original.id] == original
    assert candidate.inputs == before.inputs and candidate.eval == before.eval


def branched() -> PipelineSpec:
    candidate = app()
    candidate.blocks[1:1] = [block("shared_crop", "crop", "$sample.frame", box=[0, 0, 1, 1]),
                             block("shared_resize", "resize", "$shared_crop.image", width=160, height=100)]
    next(node for node in candidate.blocks if node.id == "det").inputs["image"] = "$shared_resize.image"
    candidate.blocks.append(block("read", "ocr", "$shared_resize.image"))
    candidate.blocks.extend([BlockSpec.model_validate({"id": "check", "type": "match",
        "params": {"expected": "SKU-001", "mode": "exact", "emit": "mismatched"}, "in": {"text": "$read.text"}}),
        BlockSpec.model_validate({"id": "reading_out", "type": "sink_event", "params": {}, "in": {"event": "$check.event"}})])
    return candidate


def test_shared_preprocessing_is_copied_only_along_target_branch() -> None:
    candidate = branched()
    before = {node.id: node.model_copy(deep=True) for node in candidate.blocks}
    apply_preprocessing(candidate, RefinementPatch(kind="crop", block_id="det", crop_box=[0, 0, .5, 1]))
    nodes = {node.id: node for node in candidate.blocks}
    for identifier, original in before.items():
        if identifier != "det":
            assert nodes[identifier] == original
    assert nodes["det"].params == before["det"].params
    assert nodes["det"].inputs == {"image": "$refined_resize.image"}
    assert nodes["refined_resize"].params == before["shared_resize"].params
    assert nodes["refined_resize"].inputs == {"image": "$refined_crop.image"}
    assert nodes["refined_crop"].inputs == {"image": "$sample.frame"}
    assert nodes["refined_crop"].params == {"box": [0, 0, .5, 1]}
    assert len(candidate.blocks) == len(before) + 2


def test_noop_on_shared_transform_preserves_exact_graph() -> None:
    candidate = branched()
    before = candidate.model_copy(deep=True)
    apply_preprocessing(candidate, RefinementPatch(kind="crop", block_id="det", crop_box=[0, 0, 1, 1]))
    assert candidate == before


@pytest.mark.parametrize("target", [None, "shared_crop", "absent", "count"])
def test_ambiguous_or_unsupported_target_never_changes_graph(target: str | None) -> None:
    candidate = branched()
    before = candidate.model_copy(deep=True)
    with pytest.raises(ValueError):
        apply_preprocessing(candidate, RefinementPatch(kind="crop", block_id=target, crop_box=[0, 0, .5, 1]))
    assert candidate == before


def test_multiple_transforms_require_explicit_transform_and_input_coordinate_basis() -> None:
    candidate = app()
    candidate.blocks[1:1] = [block("first", "crop", "$sample.frame", box=[0, 0, .75, 1]),
                             block("second", "crop", "$first.image", box=[0, 0, .5, 1])]
    next(node for node in candidate.blocks if node.id == "det").inputs["image"] = "$second.image"
    with pytest.raises(ValueError, match="multiple crop"):
        preprocessing_target(candidate, "crop", "det")
    patch = RefinementPatch(kind="crop", block_id="second", crop_box=[0, 0, .5, 1])
    with pytest.raises(ValueError, match="already-cropped"):
        validate("Set second crop to the left half", [patch], candidate)
    validate("Set second crop to the left half of its input image", [patch], candidate)
    apply_preprocessing(candidate, patch)
    assert len([node for node in candidate.blocks if node.type == "crop"]) == 2


@pytest.mark.parametrize("reference", ["$missing.image", "$sample.image", "$det.image", "bad", "$sample.frame.extra"])
def test_invalid_image_paths_reject(reference: str) -> None:
    candidate = app()
    next(node for node in candidate.blocks if node.id == "det").inputs["image"] = reference
    with pytest.raises(ValueError):
        preprocessing_target(candidate, "crop", None)


def test_cyclic_preprocessing_rejects_without_looping() -> None:
    candidate = branched()
    next(node for node in candidate.blocks if node.id == "shared_crop").inputs["image"] = "$shared_resize.image"
    with pytest.raises(ValueError, match="cyclic"):
        preprocessing_target(candidate, "crop", "det")


@pytest.mark.parametrize("name,box", [("left", [0, 0, .5, 1]), ("right", [.5, 0, 1, 1]),
    ("top", [0, 0, 1, .5]), ("bottom", [0, .5, 1, 1])])
def test_clear_half_requests_have_exact_normalized_geometry(name: str, box: list[float]) -> None:
    validate(f"Crop to the {name} half before detection", [RefinementPatch(kind="crop", crop_box=box)])


def test_literal_bounds_dimensions_compound_request_and_clarification() -> None:
    patches = [RefinementPatch(kind="crop", crop_box=[.1, .2, .8, .9]),
               RefinementPatch(kind="resize", width=640, height=480)]
    validate("Crop to [.1, .2, .8, .9] then resize to 640 × 480", patches)
    validate("Crop before detection and resize it\nUser clarification: [.1, .2, .8, .9], width 640 height 480", patches)
    validate("Resize to 320x240\nUser clarification: Use 640x480 instead", [patches[1]])
    with pytest.raises(ValueError, match="do not omit"):
        validate("Crop to [.1, .2, .8, .9] then resize to 640x480", [patches[0]])


@pytest.mark.parametrize("prompt,patch", [
    ("Crop a little tighter", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Crop to the right half", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Don't crop; set confidence to .5", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Crop to the left half or right half", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Crop to the left half of lane A", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Crop to the left half of each pallet", RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])),
    ("Resize to fit", RefinementPatch(kind="resize", width=640, height=480)),
    ("Resize to -640x480", RefinementPatch(kind="resize", width=640, height=480)),
    ("Resize to 640x480", RefinementPatch(kind="resize", width=480, height=640)),
    ("Resize to 640x480 and preserve aspect ratio", RefinementPatch(kind="resize", width=640, height=480)),
    ("Set confidence to .5", RefinementPatch(kind="resize", width=640, height=480)),
])
def test_no_invented_or_contradictory_preprocessing(prompt: str, patch: RefinementPatch) -> None:
    with pytest.raises(ValueError):
        validate(prompt, [patch])


def test_arbitrary_model_target_and_negative_branch_instructions_reject() -> None:
    candidate = branched()
    patch = RefinementPatch(kind="resize", block_id="read", width=640, height=480)
    for prompt in ["Resize to 640x480", "Resize to 640x480, not read", "Resize to 640x480; keep OCR unchanged"]:
        with pytest.raises(ValueError):
            validate(prompt, [patch], candidate)
    validate("Resize OCR to 640x480; leave det unchanged", [patch], candidate)
    validate("Resize read to 640x480", [patch], candidate)


def test_quoted_literal_and_preserved_crop_are_not_preprocessing_requests() -> None:
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    validate('Change expected text to "left half"', [RefinementPatch(kind="expected_text", expected_text="left half")], candidate)
    for prompt in ["Keep crop unchanged; set confidence to .5", "Store a crop; set confidence to .5"]:
        validate(prompt, [RefinementPatch(kind="confidence", confidence=.5)])


def workspace(tmp_path: Path) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Preprocessing software fixture", "custom")
    service.demo(project.id)
    candidate = app()
    alternative = candidate.model_copy(update={"name": "second"}, deep=True)
    service.save_candidates(project.id, [candidate, alternative], "Detect pallets")
    DatasetService(service).manifest(project.id)
    return service, project.id


def test_real_fixture_preview_crops_pixels_maps_boxes_and_previews_every_alternative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.runtime.executor as executor

    service, project_id = workspace(tmp_path)
    assert service.evaluate(project_id).passed
    service.deploy(project_id, 0, approved=True, override_reason="Isolated synthetic preprocessing software trial", approval_scope="local_trial")
    before = service.get_project(project_id)
    labels = service.annotations(project_id)
    baseline = service.preview(project_id, 0)
    assert any(detection.box[0] > .5 for detection in baseline.frames[0].detections)
    infer = executor.run_inference
    seen_sizes = []

    def observed(image: object, *args: object, **kwargs: object) -> object:
        seen_sizes.append(image.size)
        return infer(image, *args, **kwargs)

    monkeypatch.setattr(executor, "run_inference", observed)
    result = refine_app(service, project_id, RefinementBatch(patches=[
        RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1]),
        RefinementPatch(kind="resize", width=160, height=200),
    ]))
    assert result.previewed_candidate_indices == result.affected_candidate_indices == [0, 1]
    assert len(result.preview.frames) == 5 and not result.requires_review
    assert seen_sizes == [(160, 200)] * 10  # Real detector received resized crop pixels.
    for frame, original in zip(result.preview.frames, baseline.frames, strict=True):
        expected = [detection for detection in original.detections if detection.box[2] <= .5]
        assert frame.detections and len(frame.detections) == len(expected)
        inference = frame.inferences[0]
        assert inference.block_id == "det" and inference.input_to_frame == (0, 0, .5, 1)
        for detection, raw in zip(frame.detections, inference.result.detections, strict=True):
            assert detection.box == pytest.approx([raw.box[0] * .5, raw.box[1], raw.box[2] * .5, raw.box[3]])
        for detection, old in zip(frame.detections, expected, strict=True):
            assert detection.box == pytest.approx(old.box, abs=.01)  # Fixture palette loses antialiased boundary pixels.
    after = service.get_project(project_id)
    for candidate, original in zip(after.candidates, before.candidates, strict=True):
        assert candidate.inputs == original.inputs
        for old in original.blocks:
            actual = next(node for node in candidate.blocks if node.id == old.id)
            assert actual.params == old.params
            if old.id != "det":
                assert actual == old
    assert service.annotations(project_id) == labels
    assert not after.evaluations and after.deployment_id is None and not service.events(project_id)
    assert not (service.root(project_id) / "deployment.json").exists()
    assert not (service.root(project_id) / "eval-media.json").exists()


@pytest.mark.parametrize("failure", ["preview", "concurrent_pixels"])
def test_preprocessing_failure_or_concurrent_input_change_never_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    from PIL import Image

    import engine.builds.refinement as module
    service, project_id = workspace(tmp_path)
    before = service.get_project(project_id)
    labels = service.annotations(project_id)
    run = module.run_pipeline
    calls = 0

    def preview(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if failure == "preview" and calls == 2:
            raise ValueError("second preview failed")
        result = run(*args, **kwargs)
        if failure == "concurrent_pixels":
            path = before.media[0]
            with Image.open(path) as image:
                image.putpixel((0, 0), (120, calls, 20))
                image.save(path)
        return result

    monkeypatch.setattr(module, "run_pipeline", preview)
    with pytest.raises(ValueError if failure == "preview" else DatasetConflict):
        refine_app(service, project_id, RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1]))
    assert service.get_project(project_id) == before
    assert service.annotations(project_id) == labels


async def test_captured_preprocessing_decision_executes_through_guarded_mcp_transaction(tmp_path: Path) -> None:
    from agent.machine import AgentState
    from agent.mcp_client import connect_tools
    from engine.builds.store import BuildStore
    from spec.refinement import RefinementResult

    service, project_id = workspace(tmp_path)
    store = BuildStore(service)
    record = store.create(project_id, "Crop to the left half before detection, then resize to 160x200")
    batch = RefinementBatch(patches=[RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1]),
                                    RefinementPatch(kind="resize", width=160, height=200)])
    decision = RefinementDecision(message="Deterministic transport fixture; not live language-model evidence",
                                  questions=[], patches=batch.patches)
    call = store.start_model_call(project_id, record.view.id, "deterministic-test-refinement",
                                 {"prompt": record.prompt, "test_stub": True})
    store.finish_call(project_id, record.view.id, call.id, {"decision": decision.model_dump(mode="json")})
    store.record_refinement_decision(project_id, record.view.id, decision.model_dump(mode="json"))
    async with connect_tools(str(tmp_path), AgentState()) as tools:
        await tools.bind_build(project_id, record.view.id)
        result = RefinementResult.model_validate(await tools.call("build_refine", {
            "project_id": project_id, "build_id": record.view.id,
            "candidate_index": 0, "batch": batch.model_dump(mode="json"),
        }))
    assert result.previewed_candidate_indices == [0, 1]
    assert result.preview.frames[0].detections
    assert all(item.box[2] <= .5 for item in result.preview.frames[0].detections)
    captured = store.get(project_id).operation.calls[-1]
    assert captured.name == "build_refine" and captured.status == "completed"
    assert captured.result and captured.result["spec_hashes"] == result.spec_hashes
    assert captured.request["batch"] == batch.model_dump(mode="json")


def test_compound_preprocessing_rejects_wrong_insert_order_before_execution() -> None:
    candidate = build_template("labels", "media", "fixture-color-v1")[0]
    crop = RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])
    resize = RefinementPatch(kind="resize", width=1200, height=400)
    prompt = "Crop the left half then resize to 1200x400 before OCR"
    before = candidate.model_copy(deep=True)
    with pytest.raises(ValueError, match="crop/resize order"):
        validate(prompt, [resize, crop], candidate)
    assert candidate == before
    validate(prompt, [crop, resize], candidate)
    validate("Resize to 1200x400 after cropping the left half before OCR", [crop, resize], candidate)
    validate("Resize to 1200x400 then crop the left half before OCR", [resize, crop], candidate)


@pytest.mark.parametrize("existing", ["both", "resize_only", "crop_only"])
def test_existing_transform_order_cannot_be_silently_reordered(existing: str) -> None:
    candidate = app()
    crop = RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])
    resize = RefinementPatch(kind="resize", width=1200, height=400)
    if existing in {"both", "resize_only"}:
        apply_preprocessing(candidate, resize)
    if existing in {"both", "crop_only"}:
        apply_preprocessing(candidate, crop)
    before = candidate.model_copy(deep=True)
    if existing == "crop_only":
        prompt = "Resize to 1200x400 then crop the left half before detection"
    else:
        prompt = "Crop the left half then resize to 1200x400 before detection"
    with pytest.raises(ValueError, match="existing transforms cannot be reordered"):
        validate(prompt, [crop, resize], candidate)
    assert candidate == before


def test_existing_correct_order_is_independent_of_update_patch_order() -> None:
    candidate = app()
    crop = RefinementPatch(kind="crop", crop_box=[0, 0, .5, 1])
    resize = RefinementPatch(kind="resize", width=1200, height=400)
    apply_preprocessing(candidate, crop)
    apply_preprocessing(candidate, resize)
    validate("Crop the left half then resize to 1200x400", [resize, crop], candidate)
