"""A0 model-visible graph guidance, separate from the shared response schema.

The legacy planner budgets its complete output schema. These explanations belong
in A0's visible contracts and must not enlarge that shared grammar transport.
"""

from typing import Any

from spec.authoring import GraphCandidate

NODE_DESCRIPTIONS = {
    "BarcodeNode": "Decode supported machine-readable codes in the input image. Ordinary printed text requires "
    "a text reader. Decoded text is included in preview output without an event sink.",
    "CountNode": "Aggregate detections into counts by region; consumes the final zone-filtered detections when "
    "a zone filter is present.",
    "CropNode": "Extract a static rectangular region before inference. The box is relative to this node's input "
    "image, not necessarily the original source. This does not locate objects dynamically.",
    "DetectNode": "Run the selected detector on the input image and return detections for the requested "
    "supported classes.",
    "EventNode": "Receive an event produced by match or rule. Text is not an event. Optional for plain "
    "detection, counting or reading output; investigation previews never dispatch external events.",
    "MatchNode": "Compare text readings with a fixed expected string and produce match events. This does not "
    "filter or replace the original text readings in preview output.",
    "OCRNode": "Read all detected text in the input image. This node does not semantically select a requested "
    "field or discard unrelated text. Its text readings are included in preview output without "
    "requiring an event sink.",
    "ResizeNode": "Resize an image to the given pixel dimensions before downstream inference.",
    "RuleNode": "Test counts against a threshold and produce an event. Connect its event output to a sink_event "
    "node. Count-only applications do not need a rule.",
    "SampleNode": "The graph's single source. The host supplies selected media; no path or media ID belongs in "
    "a node reference. Its frame output has image type.",
    "ZoneNode": "Filter detections using the project's already confirmed region geometry.",
}

FIELD_DESCRIPTIONS = {
    "BarcodeNode": {
        "image": "Reference to an image output of another graph node, never a media ID or filename. "
        "Use the upstream node's exact output port."
    },
    "CountNode": {"dets": "Reference to a detections output: $node_id.dets."},
    "CropNode": {
        "box": "Normalized [left, top, right, bottom] with positive area within [0,1].",
        "image": "Reference to an image output of another node: $node_id.port.",
    },
    "DetectNode": {
        "image": "Reference to an image output of another graph node, never a media ID or filename. "
        "Use the upstream node's exact output port."
    },
    "EventNode": {
        "event": "Reference to an event output: $node_id.event; never a text, image or detections "
        "output."
    },
    "MatchNode": {"text": "Reference to a text output: $node_id.text."},
    "OCRNode": {
        "image": "Reference to an image output of another graph node, never a media ID or filename. Use "
        "the upstream node's exact output port."
    },
    "ResizeNode": {"image": "Reference to an image output of another node: $node_id.port."},
    "RuleNode": {"counts": "Reference to a counts output: $node_id.counts."},
    "ZoneNode": {"dets": "Reference to a detections output: $node_id.dets."},
}

GRAPH_DESCRIPTION = "One connected, acyclic vision graph. Output references must resolve to compatible ports on nodes in this graph. The host binds source media separately."
NODES_DESCRIPTION = "Include exactly one frame_sample source and one to four detector/reader nodes. Connect each image operation to inference. References use $node_id.port and must match the source port's type. At most one detect, zone_filter, count_per_zone and rule node. An event sink is optional for plain reader/detection/count output."


def graph_contract_schema() -> dict[str, Any]:
    """Add documentation to a fresh schema; validation constraints stay intact."""
    schema = GraphCandidate.model_json_schema()
    schema["description"] = GRAPH_DESCRIPTION
    schema["properties"]["nodes"]["description"] = NODES_DESCRIPTION
    for name, description in NODE_DESCRIPTIONS.items():
        schema["$defs"][name]["description"] = description
    for name, fields in FIELD_DESCRIPTIONS.items():
        for field, description in fields.items():
            schema["$defs"][name]["properties"][field]["description"] = description
    return schema
