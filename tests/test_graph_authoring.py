"""Composed authoring binds captured capabilities and preserves described scope."""
from copy import deepcopy
from pathlib import Path
from time import time

import pytest
from PIL import Image, ImageDraw
from pydantic import JsonValue, ValidationError

from agent.contracts import PlanDecision
from agent.decisions import plan_from_context
from agent.graph_authoring import compose_graph, graph_model_selections
from agent.graph_intent import validate_graph_intent
from agent.machine import AgentState
from agent.replay import replay_operation
from agent.state_contracts import AgentOperation, CapturedCall
from engine.compiler import compile_pipeline
from engine.platform.planning_options import options_digest
from engine.runtime.executor import execute_frame
from engine.runtime.values import ExecutionState
from spec.authoring import GraphCandidate
from spec.model_bindings import validate_block_bindings
from spec.planning import PlanningModelOption, PlanningOptions

NodeWire = dict[str, JsonValue]


def options() -> PlanningOptions:
    result = PlanningOptions(schema_version="0.3", snapshot_id="", project_id="software-composition", fixture_source=True,
        eligible_models=[
            PlanningModelOption(capability_id="model.apple-vision", model_id="apple-vision", adapter_id="apple-vision",
                task_types=["ocr", "barcode"], output_contract="texts/v1", vocabulary="not_applicable",
                readiness="ready", selection_basis="default"),
            PlanningModelOption(capability_id="model.fixture-color-v1", model_id="fixture-color-v1", adapter_id="fixture-color-v1",
                task_types=["detection"], output_contract="detections/v1", vocabulary="closed", supported_classes=["pallet"],
                synthetic=True, readiness="ready", selection_basis="default")], blocked_options=[])
    result.snapshot_id = options_digest(result)
    return result


def sample() -> NodeWire:
    return {"type": "frame_sample", "id": "sample", "fps": 2}


def reader(identifier: str = "read", kind: str = "ocr", image: str = "$sample.frame") -> NodeWire:
    return {"type": kind, "id": identifier, "image": image, "model_capability_id": "model.apple-vision",
            "model_reason": "Propose the captured reader capability; no quality claim"}


def detector(image: str = "$sample.frame") -> NodeWire:
    return {"type": "detect", "id": "det", "image": image, "model_capability_id": "model.fixture-color-v1",
            "model_reason": "Synthetic software execution test", "classes": ["pallet"], "min_confidence": .4}


def crop(box: list[float] | None = None) -> NodeWire:
    return {"type": "crop", "id": "roi", "image": "$sample.frame", "box": box or [0, 0, .5, 1]}


def resize(width: int = 1200, height: int = 800) -> NodeWire:
    return {"type": "resize", "id": "large", "image": "$roi.image", "width": width, "height": height}


def match() -> NodeWire:
    return {"type": "match", "id": "check", "text": "$read.text", "expected": "ABC-990", "mode": "exact", "emit": "all"}


def graph(nodes: list[NodeWire], metric: str = "text_accuracy", target: float = .95) -> GraphCandidate:
    return GraphCandidate.model_validate({"name": "Composed software candidate", "nodes": nodes, "metric": metric, "target": target})


def decision(value: GraphCandidate) -> PlanDecision:
    return PlanDecision(schema_version="0.2", message="Proposal, not a measured result", graphs=[value])


def mixed() -> GraphCandidate:
    return graph([sample(), detector(), reader(), reader("codes", "barcode")], "recall", .9)


def test_crop_resize_reader_reconstructs_exact_spec_from_host_source() -> None:
    proposed = graph([reader(image="$large.image"), resize(), crop(), sample()])
    captured = options()
    spec = compose_graph(proposed, "imported/source.png", captured)
    assert spec.model_dump(mode="json", by_alias=True) == {
        "spec_version": "0.1", "name": "Composed software candidate",
        "inputs": {"source": {"type": "image_file", "path": "imported/source.png"}},
        "blocks": [
            {"id": "sample", "type": "frame_sample", "params": {"fps": 2.0}, "in": {"frames": "$inputs.source"}},
            {"id": "roi", "type": "crop", "params": {"box": [0., 0., .5, 1.]}, "in": {"image": "$sample.frame"}},
            {"id": "large", "type": "resize", "params": {"width": 1200, "height": 800}, "in": {"image": "$roi.image"}},
            {"id": "read", "type": "ocr", "params": {"model": "apple-vision"}, "in": {"image": "$large.image"}}],
        "eval": {"set": "reviewed-v1", "metric": "text_accuracy", "target": .95}}
    planned = plan_from_context(decision(proposed), "Read printed text from the left half. Resize to 1200 by 800 pixels. Do not create events or send alerts.",
                                "imported/source.png", "ignored-host-model", {}, captured)
    assert planned.candidates == [spec] and not planned.questions


@pytest.mark.parametrize("source,source_type", [("images", "image_folder"), ("clip.MOV", "video_file"), ("image.JPG", "image_file")])
def test_only_host_argument_supplies_pipeline_source(source: str, source_type: str) -> None:
    proposed = graph([sample(), reader()])
    spec = compose_graph(proposed, source, options())
    assert spec.inputs["source"].path == source and spec.inputs["source"].type == source_type
    payload = proposed.model_dump(mode="json")
    payload["inputs"] = {"source": {"type": "image_file", "path": "/generated/path"}}
    with pytest.raises(ValidationError, match="Extra inputs"):
        GraphCandidate.model_validate(payload)


def test_every_inference_node_has_its_own_model_binding() -> None:
    proposed, captured = mixed(), options()
    selections = graph_model_selections([proposed], captured)
    assert [(row.candidate_index, row.block_id, row.model_id) for row in selections] == [
        (0, "det", "fixture-color-v1"), (0, "read", "apple-vision"), (0, "codes", "apple-vision")]
    assert all(row.options_snapshot_id == captured.snapshot_id and row.status == "proposed" for row in selections)
    validate_block_bindings(compose_graph(proposed, "media", captured), selections, 0, captured)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "swapped", "wrong_candidate", "snapshot", "adapter", "capability"])
def test_incomplete_or_changed_block_bindings_are_rejected(mutation: str) -> None:
    proposed, captured = mixed(), options()
    selections = graph_model_selections([proposed], captured)
    if mutation == "missing":
        selections.pop()
    elif mutation == "duplicate":
        selections[-1] = selections[0].model_copy()
    elif mutation == "swapped":
        selections[0].block_id, selections[1].block_id = selections[1].block_id, selections[0].block_id
    elif mutation == "wrong_candidate":
        selections[0].candidate_index = 1
    elif mutation == "snapshot":
        selections[0].options_snapshot_id = "unrelated-snapshot"
    elif mutation == "adapter":
        selections[0].adapter_id = "other-adapter"
    else:
        selections[0].capability_id = "model.not-captured"
    with pytest.raises(ValueError):
        validate_block_bindings(compose_graph(proposed, "media", captured), selections, 0, captured)


def test_changed_graph_model_is_rejected_even_without_reloaded_options() -> None:
    proposed, captured = mixed(), options()
    selections = graph_model_selections([proposed], captured)
    spec = compose_graph(proposed, "media", captured)
    next(block for block in spec.blocks if block.id == "det").params["model"] = "unrecorded-model"
    with pytest.raises(ValueError, match="graph's model differs"):
        validate_block_bindings(spec, selections, 0)


def test_selections_for_other_candidates_cannot_fill_missing_nodes() -> None:
    proposed, captured = mixed(), options()
    all_selections = graph_model_selections([proposed, proposed], captured)
    spec = compose_graph(proposed, "media", captured)
    validate_block_bindings(spec, all_selections, 1, captured)
    without_reader = [row for row in all_selections if not (row.candidate_index == 1 and row.block_id == "read")]
    with pytest.raises(ValueError, match="cover every inference block"):
        validate_block_bindings(spec, without_reader, 1, captured)


@pytest.mark.parametrize("node,capability", [(reader(), "model.fixture-color-v1"), (detector(), "model.apple-vision"), (reader(), "model.invented")])
def test_model_capability_must_exist_and_implement_the_node_task(node: NodeWire, capability: str) -> None:
    changed = deepcopy(node)
    changed["model_capability_id"] = capability
    proposed = graph([sample(), changed], "recall" if changed["type"] == "detect" else "text_accuracy", .9)
    with pytest.raises(ValueError, match="does not implement|Unknown or unsupported"):
        graph_model_selections([proposed], options())


def test_fixture_selection_needs_fixture_media_and_compatible_class_vocabulary() -> None:
    proposed = graph([sample(), detector()], "recall", .9)
    captured = options()
    captured.fixture_source = False
    with pytest.raises(ValueError, match="real project media"):
        graph_model_selections([proposed], captured)
    changed = detector()
    changed["classes"] = ["forklift"]
    with pytest.raises(ValueError, match="does not cover the requested classes"):
        graph_model_selections([graph([sample(), changed], "recall", .9)], options())


def test_graph_planning_requires_current_captured_options_and_version() -> None:
    proposed = graph([sample(), reader()])
    with pytest.raises(ValueError, match="captured capability options"):
        plan_from_context(decision(proposed), "Read printed text.", "media", "irrelevant", {})
    old = options().model_copy(update={"schema_version": "0.2"})
    with pytest.raises(ValueError, match="current captured"):
        graph_model_selections([proposed], old)
    with pytest.raises(ValidationError, match="version 0.2"):
        PlanDecision(message="Missing version", graphs=[proposed])
    with pytest.raises(ValidationError, match="legacy pattern"):
        PlanDecision.model_validate({"schema_version": "0.2", "message": "Conflicting version",
            "choices": [{"use_case": "custom", "objects": ["pallet"], "metric": "recall", "target": .9}]})
    question = PlanDecision(schema_version="0.2", message="Need one detail", questions=["Which text should be compared?"])
    assert plan_from_context(question, "Compare text", "media", "unused").questions == question.questions


def test_legacy_decision_reconstructs_and_replays_same_historical_spec() -> None:
    legacy = PlanDecision.model_validate({"message": "Count pallets", "choices": [
        {"use_case": "custom", "objects": ["pallet"], "metric": "count_mae", "target": .5}]})
    assert legacy.schema_version == "0.1" and not legacy.graphs and legacy.choices[0].record_events is None
    result = plan_from_context(legacy, "Count pallets. Do not create events or send alerts.", "media", "fixture-color-v1")
    spec = result.candidates[0]
    assert [(block.id, block.type) for block in spec.blocks] == [("sample", "frame_sample"), ("det", "detect"), ("count", "count_per_zone")]
    assert spec.blocks[1].params == {"model": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}
    assert spec.blocks[2].params == {} and spec.blocks[2].inputs == {"dets": "$det.dets"}
    state = AgentState()
    state.budget.tool_calls = 2
    result.operation_id, result.tool_calls = "old-operation", 2
    wire = spec.model_dump(mode="json", by_alias=True)
    operation = AgentOperation(id="old-operation", project_id="software", trace_id="trace", root_span_id="span", owner_pid=1,
        deadline=time() + 30, status="completed", input_fingerprint="captured", brief="Count pallets. Do not create events or send alerts.",
        source_path="media", detector_model="fixture-color-v1", state=state, decision=legacy, result=result,
        calls=[CapturedCall(id="validate", kind="tool", name="pipeline_validate", started_ns=1, ended_ns=2,
                           status="completed", request={"spec": wire}, result={"valid": True}),
               CapturedCall(id="preview", kind="tool", name="pipeline_run", started_ns=3, ended_ns=4,
                            status="completed", request={"spec": wire}, result={"frames": [{"software_fixture": True}]})])
    replay = replay_operation(operation)
    assert replay.reproduced and replay.result == result and not replay.effects_executed


def test_compare_without_events_retains_comparison_and_rejects_sink() -> None:
    proposed = graph([sample(), reader(), match()])
    brief = "Read printed labels and compare against ABC-990 exactly. Do not create events or send alerts."
    result = plan_from_context(decision(proposed), brief, "media", "unused", {}, options())
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", "ocr", "match"]
    assert result.candidates[0].blocks[-1].params == {"expected": "ABC-990", "mode": "exact", "emit": "all"}
    with_sink = graph([sample(), reader(), match(), {"id": "out", "type": "sink_event", "event": "$check.event"}])
    with pytest.raises(ValueError, match="No local events were requested"):
        plan_from_context(decision(with_sink), brief, "media", "unused", {}, options())


def test_user_requested_reading_event_cannot_be_dropped() -> None:
    check = match()
    check["emit"] = "matched"
    proposed = graph([sample(), reader(), check])
    with pytest.raises(ValueError, match="requested local events"):
        validate_graph_intent([proposed], "Read printed labels and compare against ABC-990 exactly; create a local event when it matches.", {})


def test_saved_zone_names_need_actual_boundaries_and_host_owns_zone_path() -> None:
    proposed = graph([sample(), detector(), {"id": "zones", "type": "zone_filter", "dets": "$det.dets", "zone_ids": ["A"]},
                      {"id": "count", "type": "count_per_zone", "dets": "$zones.dets", "include_unassigned": False}], "count_mae", .5)
    brief = "Count pallets in region A. Do not create events or send alerts."
    missing = plan_from_context(decision(proposed), brief, "media", "unused", {"zones_confirmed": False, "saved_zone_ids": []}, options())
    assert missing.needs_zones and not missing.candidates and "A" in missing.questions[0]
    result = plan_from_context(decision(proposed), brief, "media", "unused", {"zones_confirmed": True, "saved_zone_ids": ["A"]}, options())
    zone = next(block for block in result.candidates[0].blocks if block.type == "zone_filter")
    assert zone.params == {"zones": "zones/lanes.json", "include_ids": ["A"]}
    payload = proposed.model_dump(mode="json")
    payload["nodes"][2]["zones"] = "/generated/other-zones.json"
    with pytest.raises(ValidationError, match="Extra inputs"):
        GraphCandidate.model_validate(payload)


@pytest.mark.parametrize("kind,error", [("ocr", "barcode reading"), ("barcode", "printed text recognition")])
def test_joint_reading_request_cannot_omit_either_reader(kind: str, error: str) -> None:
    brief = "Read printed text and barcodes. Do not create events or send alerts."
    with pytest.raises(ValueError, match=error):
        validate_graph_intent([graph([sample(), reader(kind=kind)])], brief, {})
    both = graph([sample(), reader(), reader("codes", "barcode")])
    result = plan_from_context(decision(both), brief, "media", "unused", {}, options())
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", "ocr", "barcode"]


def test_joint_counting_and_reading_request_cannot_omit_detector() -> None:
    with pytest.raises(ValueError, match="detect|count"):
        validate_graph_intent([graph([sample(), reader()])], "Count pallets and read printed text. Do not create events or send alerts.", {})


@pytest.mark.parametrize("brief", [
    "Read printed text from the left half.",
    "Crop [0.1, 0.2, 0.6, 0.8] and read printed text.",
    "Resize to 1200 by 800 pixels and read printed text.",
    "Resize to 8 by 16 pixels and read printed text.",
])
def test_explicit_image_transform_cannot_be_omitted(brief: str) -> None:
    with pytest.raises(ValueError, match="crop|resize|width|half"):
        validate_graph_intent([graph([sample(), reader()])], brief, {})


def test_wrong_crop_coordinates_and_resize_dimensions_are_rejected() -> None:
    wrong_crop = graph([sample(), crop([.1, .2, .7, .8]), reader(image="$roi.image")])
    with pytest.raises(ValueError, match="crop coordinates"):
        validate_graph_intent([wrong_crop], "Crop [0.1, 0.2, 0.6, 0.8] and read printed text.", {})
    wrong_resize = graph([sample(), crop(), resize(800, 1200), reader(image="$large.image")])
    with pytest.raises(ValueError, match="resize width and height"):
        validate_graph_intent([wrong_resize], "Read printed text from the left half. Resize to 1200 by 800 pixels.", {})


def test_alternatives_preserve_task_scope_but_may_test_detector_confidence() -> None:
    first = graph([sample(), detector()], "recall", .9)
    second_node = detector()
    second_node["min_confidence"] = .7
    second = graph([sample(), second_node], "recall", .9)
    assert len(graph_model_selections([first, second], options())) == 2
    changed_scope = graph([sample(), crop(), detector("$roi.image")], "recall", .9)
    with pytest.raises(ValueError, match="same composed task"):
        graph_model_selections([first, changed_scope], options())


def test_composed_crop_resize_fixture_detector_executes_on_actual_pixels(tmp_path: Path) -> None:
    proposed = graph([sample(), crop(), resize(160, 200), detector("$large.image"),
                      {"id": "count", "type": "count_per_zone", "dets": "$det.dets", "include_unassigned": False}], "count_mae", .5)
    path = tmp_path / "fixture.png"
    image = Image.new("RGB", (160, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 39, 39), fill=(36, 166, 112))
    draw.rectangle((120, 70, 139, 89), fill=(36, 166, 112))
    image.save(path)
    spec = compose_graph(proposed, str(path), options())
    validate_block_bindings(spec, graph_model_selections([proposed], options()), 0, options())
    result = execute_frame(compile_pipeline(spec, tmp_path), path, 0, ExecutionState())
    assert len(result.detections) == 1 and result.detections[0].label == "pallet"
    assert result.detections[0].box == pytest.approx([.125, .2, .25, .4], abs=.015)
    assert result.counts == {"all": 1} and result.events == []
    assert result.inferences[0].block_id == "det" and result.inferences[0].input_to_frame == (0., 0., .5, 1.)
    assert result.inferences[0].result.identity.model_id == "fixture-color-v1"
    assert result.inferences[0].result.identity.identity_scope == "synthetic_code"
