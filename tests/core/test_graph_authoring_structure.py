"""Composition contracts reject invalid graphs before any engine execution."""
from copy import deepcopy

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from agent.graph_structure import OUTPUTS, inputs, ordered_nodes
from engine.blocks.registry import REGISTRY
from spec.authoring import GraphCandidate, GraphNode

NodeWire = dict[str, JsonValue]


def test_every_node_discriminator_precedes_shared_fields_for_constrained_decoding() -> None:
    schema = TypeAdapter(GraphNode).json_schema()
    variants = [definition for definition in schema["$defs"].values()
                if "type" in definition.get("properties", {})]
    assert len(variants) == len(OUTPUTS)
    for definition in variants:
        assert next(iter(definition["properties"])) == "type"
        assert definition["required"][0] == "type"
        assert definition["properties"]["type"]["const"] in OUTPUTS


def sample(identifier: str = "sample") -> NodeWire:
    return {"id": identifier, "type": "frame_sample", "fps": 2}


def reader(identifier: str = "read", kind: str = "ocr", image: str = "$sample.frame") -> NodeWire:
    return {"id": identifier, "type": kind, "image": image,
            "model_capability_id": "model.apple-vision", "model_reason": "Test an installed reader"}


def detector(identifier: str = "det") -> NodeWire:
    return {"id": identifier, "type": "detect", "image": "$sample.frame",
            "model_capability_id": "model.owlv2-base-patch16", "model_reason": "Test the requested class",
            "classes": ["pallet"], "min_confidence": .4}


def comparison() -> NodeWire:
    return {"id": "check", "type": "match", "text": "$read.text", "expected": "ABC-990",
            "mode": "exact", "emit": "matched"}


def counting_nodes() -> list[NodeWire]:
    return [sample(), detector(),
            {"id": "zones", "type": "zone_filter", "dets": "$det.dets", "zone_ids": ["A"]},
            {"id": "count", "type": "count_per_zone", "dets": "$zones.dets", "include_unassigned": False},
            {"id": "full", "type": "rule", "counts": "$count.counts", "operator": ">=", "threshold": 3, "hold_seconds": 30},
            {"id": "out", "type": "sink_event", "event": "$full.event"}]


def candidate(nodes: list[NodeWire], metric: str = "text_accuracy", target: float = .95) -> GraphCandidate:
    return GraphCandidate.model_validate({"name": "Composition software test", "nodes": nodes,
                                          "metric": metric, "target": target})


def test_crop_resize_reader_sorts_reversed_input_without_rewriting_geometry() -> None:
    nodes = [reader(image="$large.image"),
             {"id": "large", "type": "resize", "image": "$roi.image", "width": 1200, "height": 800},
             {"id": "roi", "type": "crop", "image": "$sample.frame", "box": [.1, .2, .6, .8]}, sample()]
    graph = candidate(nodes)
    before = graph.model_dump(mode="json")
    ordered = ordered_nodes(graph)
    assert [node.id for node in ordered] == ["sample", "roi", "large", "read"]
    assert ordered[1].model_dump()["box"] == (.1, .2, .6, .8)
    assert graph.model_dump(mode="json") == before


def test_parallel_readers_keep_independent_outputs_and_comparison() -> None:
    graph = candidate([comparison(), reader("codes", "barcode"), reader(), sample()])
    ordered = ordered_nodes(graph)
    positions = {node.id: index for index, node in enumerate(ordered)}
    assert positions["sample"] < positions["read"] < positions["check"]
    assert positions["sample"] < positions["codes"]
    assert {node.type for node in ordered} == {"frame_sample", "ocr", "barcode", "match"}
    assert not any(node.type == "sink_event" for node in ordered)


def test_detector_and_reader_share_pixels_without_merging_their_outputs() -> None:
    graph = candidate([sample(), detector(), reader(),
                       {"id": "count", "type": "count_per_zone", "dets": "$det.dets", "include_unassigned": False}],
                      metric="recall", target=.9)
    ordered = ordered_nodes(graph)
    assert {node.id for node in ordered} == {"sample", "det", "read", "count"}
    assert inputs(next(node for node in ordered if node.id == "count")) == {"dets": ("$det.dets", "detections")}
    assert inputs(next(node for node in ordered if node.id == "read")) == {"image": ("$sample.frame", "image")}


@pytest.mark.parametrize("reference", ["$missing.frame", "$sample.unknown", "$read.text", "$inputs.source"])
def test_reader_rejects_missing_or_incompatible_image_port(reference: str) -> None:
    graph = candidate([sample(), reader(image=reference)])
    with pytest.raises(ValueError, match="Unresolved or incompatible input"):
        ordered_nodes(graph)


@pytest.mark.parametrize("index,field,reference", [
    (1, "image", "$count.counts"), (2, "dets", "$sample.frame"),
    (3, "dets", "$full.event"), (4, "counts", "$det.dets"), (5, "event", "$count.counts"),
])
def test_every_dataflow_port_uses_the_registered_value_type(index: int, field: str, reference: str) -> None:
    nodes = counting_nodes()
    nodes[index][field] = reference
    with pytest.raises(ValueError, match="Unresolved or incompatible input"):
        ordered_nodes(candidate(nodes, "count_mae", .5))


def test_match_cannot_consume_detection_values() -> None:
    check = comparison()
    check["text"] = "$det.dets"
    with pytest.raises(ValueError, match="expected text"):
        ordered_nodes(candidate([sample(), detector(), check], "recall", .9))


def test_image_cycle_is_rejected_despite_other_valid_branch() -> None:
    graph = candidate([sample(), reader(),
                       {"id": "a", "type": "crop", "image": "$b.image", "box": [0, 0, .5, 1]},
                       {"id": "b", "type": "resize", "image": "$a.image", "width": 100, "height": 100}])
    with pytest.raises(ValueError, match="cycle"):
        ordered_nodes(graph)


@pytest.mark.parametrize("identifier", ["inputs", "sample", "", "1read", "r" * 65])
def test_duplicate_reserved_and_invalid_node_identifiers_are_rejected(identifier: str) -> None:
    with pytest.raises(ValidationError):
        candidate([sample(), reader(identifier)])


def test_structure_rechecks_duplicate_ids_in_an_in_memory_mutated_graph() -> None:
    graph = candidate([sample(), reader()])
    graph.nodes.append(graph.nodes[1])
    with pytest.raises(ValueError, match="unique"):
        ordered_nodes(graph)


@pytest.mark.parametrize("node_count", [1, 17])
def test_candidate_node_count_is_bounded(node_count: int) -> None:
    nodes = [sample()] + [reader(f"read{i}") for i in range(node_count - 1)]
    with pytest.raises(ValidationError):
        candidate(nodes)


def test_maximum_sized_valid_chain_and_four_reader_branches_are_accepted() -> None:
    nodes = [sample()]
    previous = "$sample.frame"
    for index in range(11):
        identifier = f"resize{index}"
        nodes.append({"id": identifier, "type": "resize", "image": previous, "width": 100, "height": 100})
        previous = f"${identifier}.image"
    nodes.extend(reader(f"r{index}", image=previous) for index in range(4))
    assert len(ordered_nodes(candidate(nodes))) == 16


@pytest.mark.parametrize("fps", [0, -1, 61, float("nan"), float("inf")])
def test_sampling_rate_stays_within_runtime_bounds(fps: float) -> None:
    node = sample()
    node["fps"] = fps
    with pytest.raises(ValidationError):
        candidate([node, reader()])


@pytest.mark.parametrize("box", [
    [0, 0, 0, 1], [0, .8, 1, .2], [-.1, 0, .5, 1], [0, 0, 1.1, 1],
    [0, 0, float("nan"), 1], [0, 0, float("inf"), 1], [0, 0, 1],
])
def test_invalid_crop_is_rejected_before_compilation(box: list[float]) -> None:
    with pytest.raises(ValidationError):
        candidate([sample(), {"id": "roi", "type": "crop", "image": "$sample.frame", "box": box}, reader(image="$roi.image")])


@pytest.mark.parametrize("field,value", [("width", 0), ("height", -1), ("width", 8193), ("height", .5)])
def test_resize_requires_bounded_pixel_dimensions(field: str, value: float) -> None:
    node: NodeWire = {"id": "large", "type": "resize", "image": "$sample.frame", "width": 1200, "height": 800}
    node[field] = value
    with pytest.raises(ValidationError):
        candidate([sample(), node, reader(image="$large.image")])


@pytest.mark.parametrize("preprocessing", [
    {"id": "unused", "type": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]},
    {"id": "unused", "type": "resize", "image": "$sample.frame", "width": 200, "height": 100},
])
def test_orphan_preprocessing_cannot_be_claimed_as_part_of_the_result(preprocessing: NodeWire) -> None:
    with pytest.raises(ValueError, match="Unused image operation"):
        ordered_nodes(candidate([sample(), preprocessing, reader()]))


def test_duplicate_event_sinks_cannot_double_emit_one_comparison() -> None:
    graph = candidate([sample(), reader(), comparison(),
                       {"id": "one", "type": "sink_event", "event": "$check.event"},
                       {"id": "two", "type": "sink_event", "event": "$check.event"}])
    with pytest.raises(ValueError, match="Duplicate sinks"):
        ordered_nodes(graph)


def test_event_sinks_cannot_be_chained() -> None:
    graph = candidate([sample(), reader(), comparison(),
                       {"id": "one", "type": "sink_event", "event": "$check.event"},
                       {"id": "two", "type": "sink_event", "event": "$one.event"}])
    with pytest.raises(ValueError, match="cannot be chained"):
        ordered_nodes(graph)


def test_counts_follow_final_zone_scope() -> None:
    graph = candidate(counting_nodes(), "count_mae", .5)
    assert [node.id for node in ordered_nodes(graph)] == ["sample", "det", "zones", "count", "full", "out"]
    nodes = counting_nodes()
    nodes[3]["dets"] = "$det.dets"
    with pytest.raises(ValueError, match="Counts must consume the final zone-filtered"):
        ordered_nodes(candidate(nodes, "count_mae", .5))


def test_count_rule_requires_explicit_event_sink() -> None:
    with pytest.raises(ValueError, match="count rule needs an explicit local-event sink"):
        ordered_nodes(candidate(counting_nodes()[:-1], "count_mae", .5))


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_single_detection_and_count_projections_cannot_be_overwritten(index: int) -> None:
    nodes = counting_nodes()
    duplicate = deepcopy(nodes[index])
    duplicate["id"] = "second"
    nodes.append(duplicate)
    with pytest.raises(ValueError, match="one detector, zone filter, count aggregate and count rule"):
        ordered_nodes(candidate(nodes, "count_mae", .5))


def test_exactly_one_host_owned_frame_source_is_required() -> None:
    with pytest.raises(ValueError, match="exactly one frame_sample"):
        ordered_nodes(candidate([reader(), reader("other")]))
    with pytest.raises(ValueError, match="exactly one frame_sample"):
        ordered_nodes(candidate([sample(), sample("other"), reader()]))


def test_inference_branch_count_and_reading_metric_are_bounded() -> None:
    with pytest.raises(ValueError, match="one to four"):
        ordered_nodes(candidate([sample(), {"id": "crop", "type": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]}]))
    with pytest.raises(ValueError, match="one to four"):
        ordered_nodes(candidate([sample()] + [reader(f"r{i}") for i in range(5)]))
    with pytest.raises(ValueError, match="Reading-only graphs require text_accuracy"):
        ordered_nodes(candidate([sample(), reader()], "recall", .9))
    with pytest.raises(ValidationError, match="Ratio metric targets"):
        candidate([sample(), reader()], target=1.1)


@pytest.mark.parametrize("node,field,value", [
    (sample(), "path", "/arbitrary/source"),
    (reader(), "model_path", "/arbitrary/model"),
    ({"id": "out", "type": "sink_event", "event": "$check.event"}, "alert", "webhook:external"),
])
def test_generated_nodes_cannot_acquire_paths_or_external_delivery(node: NodeWire, field: str, value: str) -> None:
    altered = deepcopy(node)
    altered[field] = value
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        candidate([sample("source"), altered])


def test_graph_port_contracts_match_executable_registry() -> None:
    nodes = counting_nodes() + [reader(), reader("barcode", "barcode"), comparison(),
                                {"id": "crop", "type": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]},
                                {"id": "resize", "type": "resize", "image": "$crop.image", "width": 100, "height": 100}]
    graph = candidate(nodes, "count_mae", .5)
    assert {node.type for node in graph.nodes} == set(OUTPUTS)
    for node in graph.nodes:
        definition = REGISTRY[node.type]
        assert OUTPUTS[node.type] == definition.outputs
        if node.type == "frame_sample":
            assert inputs(node) == {} and definition.inputs == {"frames": "frames"}
        else:
            assert {name: value_type for name, (_, value_type) in inputs(node).items()} == definition.inputs


@pytest.mark.parametrize("node,parameters", [
    (sample(), {"fps": 2}),
    (reader(), {"model": "apple-vision"}),
    (reader("barcode", "barcode"), {}),
    (detector(), {"model": "owlv2-base-patch16", "classes": ["pallet"], "min_conf": .4}),
    (counting_nodes()[2], {"zones": "zones/lanes.json", "include_ids": ["A"]}),
    (counting_nodes()[3], {"include_unassigned": False}),
    (counting_nodes()[4], {"when": "count >= 3", "hold_s": 30}),
    (comparison(), {"expected": "ABC-990", "mode": "exact", "emit": "matched"}),
    (counting_nodes()[5], {}),
    ({"id": "crop", "type": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]}, {"box": [0, 0, .5, 1]}),
    ({"id": "resize", "type": "resize", "image": "$sample.frame", "width": 8192, "height": 8192}, {"width": 8192, "height": 8192}),
])
def test_authored_parameter_contract_has_an_executable_registry_representation(node: NodeWire, parameters: NodeWire) -> None:
    authored = TypeAdapter(GraphNode).validate_python(node)
    executable = REGISTRY[authored.type].params.model_validate(parameters).model_dump(mode="json")
    # Independent cross-contract examples document renamed keys and host bindings;
    # compilation tests must separately verify that the actual mapper emits them.
    assert all(executable[key] == value for key, value in parameters.items())
    assert not {"model_capability_id", "model_reason", "image", "dets", "counts", "text", "event"} & executable.keys()
