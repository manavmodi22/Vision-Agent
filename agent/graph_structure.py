"""Effect-free structure checks for the planner's bounded graph vocabulary."""
from spec.authoring import (
    BarcodeNode,
    CountNode,
    CropNode,
    DetectNode,
    EventNode,
    GraphCandidate,
    GraphNode,
    MatchNode,
    OCRNode,
    ResizeNode,
    RuleNode,
    SampleNode,
    ZoneNode,
)


def inputs(node: GraphNode) -> dict[str, tuple[str, str]]:
    if isinstance(node, SampleNode):
        return {}
    if isinstance(node, (CropNode, ResizeNode, DetectNode, OCRNode, BarcodeNode)):
        return {"image": (node.image, "image")}
    if isinstance(node, (ZoneNode, CountNode)):
        return {"dets": (node.dets, "detections")}
    if isinstance(node, RuleNode):
        return {"value": (node.counts, "counts")}
    if isinstance(node, MatchNode):
        return {"text": (node.text, "text")}
    return {"event": (node.event, "event")}


OUTPUTS = {"frame_sample": {"frame": "image"}, "crop": {"image": "image"},
           "resize": {"image": "image"}, "detect": {"dets": "detections"},
           "zone_filter": {"dets": "detections"}, "count_per_zone": {"counts": "counts"},
           "ocr": {"text": "text"}, "barcode": {"text": "text"},
           "match": {"event": "event"}, "rule": {"event": "event"}, "sink_event": {"event": "event"}}


def ordered_nodes(graph: GraphCandidate) -> list[GraphNode]:
    """Validate typed ports, reachability and the runtime's single count projection."""
    nodes = {node.id: node for node in graph.nodes}
    if len(nodes) != len(graph.nodes) or "inputs" in nodes:
        raise ValueError("Node IDs must be unique; inputs is reserved")
    if sum(isinstance(node, SampleNode) for node in graph.nodes) != 1:
        raise ValueError("A composed candidate needs exactly one frame_sample source")
    models = [node for node in graph.nodes if isinstance(node, (DetectNode, OCRNode, BarcodeNode))]
    if not 1 <= len(models) <= 4:
        raise ValueError("A candidate needs one to four detector/reader branches")
    for kind in (DetectNode, ZoneNode, CountNode, RuleNode):
        if sum(isinstance(node, kind) for node in graph.nodes) > 1:
            raise ValueError("Current runtime supports one detector, zone filter, count aggregate and count rule per candidate")
    dependencies: dict[str, set[str]] = {}
    consumers: dict[str, list[str]] = {key: [] for key in nodes}
    for node in graph.nodes:
        dependencies[node.id] = set()
        for reference, expected in inputs(node).values():
            owner, port = reference[1:].split(".")
            source = nodes.get(owner)
            if source is None or OUTPUTS[source.type].get(port) != expected:
                raise ValueError(f"Unresolved or incompatible input {reference} for {node.id}; expected {expected}")
            dependencies[node.id].add(owner)
            consumers[owner].append(node.id)
    result: list[GraphNode] = []
    remaining = {key: set(value) for key, value in dependencies.items()}
    while remaining:
        ready = [key for key, value in remaining.items() if not value]
        if not ready:
            raise ValueError("The proposed graph contains a cycle")
        for key in ready:
            result.append(nodes[key])
            del remaining[key]
        for value in remaining.values():
            value.difference_update(ready)
    for node in graph.nodes:
        if isinstance(node, (SampleNode, CropNode, ResizeNode)) and not consumers[node.id]:
            raise ValueError(f"Unused image operation {node.id}; connect it to the requested inference branch")
        if isinstance(node, RuleNode) and not any(isinstance(nodes[key], EventNode) for key in consumers[node.id]):
            raise ValueError("A count rule needs an explicit local-event sink; count-only output needs no rule")
        if isinstance(node, EventNode) and isinstance(nodes[node.event[1:].split('.')[0]], EventNode):
            raise ValueError("Event sinks cannot be chained")
        if sum(isinstance(nodes[key], EventNode) for key in consumers[node.id]) > 1:
            raise ValueError("Duplicate sinks would emit the same event twice")
    zone = next((node for node in graph.nodes if isinstance(node, ZoneNode)), None)
    count = next((node for node in graph.nodes if isinstance(node, CountNode)), None)
    if zone is not None and count is not None and count.dets != f"${zone.id}.dets":
        raise ValueError("Counts must consume the final zone-filtered detections, matching displayed/evaluated scope")
    if not any(isinstance(node, DetectNode) for node in models) and graph.metric != "text_accuracy":
        raise ValueError("Reading-only graphs require text_accuracy")
    return result
