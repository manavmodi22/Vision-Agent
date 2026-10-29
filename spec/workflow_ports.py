"""Input-port metadata for the typed authoring vocabulary, without engine imports.

Names are compiled ports: the host supplies frame_sample.frames, and the
authoring field RuleNode.counts binds the runtime input named value.
"""

WORKFLOW_INPUT_PORTS: dict[str, dict[str, str]] = {
    "barcode": {"image": "image"},
    "count_per_zone": {"dets": "detections"},
    "crop": {"image": "image"},
    "detect": {"image": "image"},
    "frame_sample": {"frames": "frames"},
    "match": {"text": "text"},
    "ocr": {"image": "image"},
    "resize": {"image": "image"},
    "rule": {"value": "counts"},
    "sink_event": {"event": "event"},
    "zone_filter": {"dets": "detections"},
}
