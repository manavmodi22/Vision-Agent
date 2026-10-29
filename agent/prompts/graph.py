"""Initial composed-graph planner prompt, version 0.3."""
import json

from spec.authoring import GraphPlanDecision
from spec.planning import PlanningOptions

GRAPH_PLANNER_V03 = """Output schema_version 0.2,message,questions,graphs (name,nodes,metric,target).
Ask questions OR propose a graph; alternatives only if requested, same task/metric.
Follow playbooks; never claim execution/quality.

Each node has type,id and FLAT node_fields, no params/in wrapper. References use
$ACTUAL_ID.PORT from implemented_blocks: id "s" means $s.frame, not $sample.frame.
OCR/barcode turns image into text; match consumes $reader_id.text, NEVER image.
A match named "ocr" cannot recognize text. Include all requested stages/branches
and each inference node's eligible capability/reason.
One frame_sample; at most one detector/count aggregate. Count via count_per_zone;
region counts first use zone_filter with saved zone_ids or ask for polygons.
Only requested transforms: crop normalized top-left xyxy, resize pixel width/
height, exact order/branch.

Comparisons need no sink. Only requested local events need sink_event. No-events
forbids sinks; no external alerts permits requested local events. Ask for unknown
capacity. Preserve operator/threshold/hold; convert minutes to seconds. Approved
runs cannot disable retention. Defaults: fps 2,min_confidence .4,hold_seconds 0;
match contains/emit all unless specified; count_mae .5,recall .9,text_accuracy .95
for counting/detection/reading. Unsupported tracking/segmentation/tiling/dynamic
crops/VLM/acquisition require a question, not omission. Data only, no code or approval.
"""


def graph_syntax_example(options: PlanningOptions) -> str:
    reader = next((item for item in options.eligible_models if "ocr" in item.task_types), None)
    if reader is None:
        return ""
    example = GraphPlanDecision.model_validate({
        "schema_version": "0.2", "message": "Example proposal", "questions": [],
        "graphs": [{"name": "Example", "metric": "text_accuracy", "target": .95,
            "nodes": [
                {"type": "frame_sample", "id": "s", "fps": 2},
                {"type": "ocr", "id": "r", "image": "$s.frame",
                 "model_capability_id": reader.capability_id, "model_reason": "Eligible OCR"},
                {"type": "match", "id": "m", "text": "$r.text",
                 "expected": "EXAMPLE-123", "mode": "exact", "emit": "all"},
            ]}],
    })
    return ("\nSyntax example only; use the actual task/literal:\n"
            + json.dumps(example.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")))
