"""Authored patterns, selected explicitly by the user; these are not LLM plans."""

from pathlib import PurePath

from pydantic import JsonValue

from spec.models import PipelineSpec


def build_template(use_case: str, source_path: str, model: str, classes: list[str] | None = None) -> list[PipelineSpec]:
    """Build a typed warehouse pattern without model inference or file access."""
    if use_case not in {"custom", "pallets", "damage", "labels"}:
        raise ValueError(f"Unknown use case {use_case!r}; choose custom, pallets, damage, or labels.")
    if use_case == "custom" and not classes:
        raise ValueError("Define the object classes in Dataset before creating a custom detector template.")
    if not source_path.strip():
        raise ValueError("Import media before building a pipeline.")
    suffix = PurePath(source_path).suffix.lower()
    source_type = "image_folder"
    if suffix in {".mp4", ".mov", ".avi", ".mkv"}:
        source_type = "video_file"
    elif suffix in {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"}:
        source_type = "image_file"
    blocks: list[dict[str, JsonValue]] = [
        {"id": "sample", "type": "frame_sample", "params": {"fps": 2},
         "in": {"frames": "$inputs.source"}},
    ]
    if use_case == "labels":
        blocks.extend([
            {"id": "read", "type": "ocr", "params": {}, "in": {"image": "$sample.frame"}},
            {"id": "check", "type": "match", "params": {"expected": "SKU-001", "mode": "contains"},
             "in": {"text": "$read.text"}},
            {"id": "out", "type": "sink_event", "params": {}, "in": {"event": "$check.event"}},
        ])
        metric, target = "text_accuracy", 0.95
    else:
        labels: list[JsonValue] = list[JsonValue](classes) if classes else (["pallet"] if use_case == "pallets" else ["damaged carton", "damaged pallet"])
        blocks.extend([
            {"id": "det", "type": "detect", "params": {"model": model, "classes": labels, "min_conf": 0.4},
             "in": {"image": "$sample.frame"}},
        ])
        if use_case == "pallets":
            blocks.append({"id": "zones", "type": "zone_filter", "params": {"zones": "zones/lanes.json"},
                           "in": {"dets": "$det.dets"}})
        blocks.extend([
            {"id": "count", "type": "count_per_zone", "params": {},
             "in": {"dets": "$zones.dets" if use_case == "pallets" else "$det.dets"}},
            {"id": "full", "type": "rule", "params": {"when": "count >= 3" if use_case == "pallets" else "count >= 1", "hold_s": 0},
             "in": {"value": "$count.counts"}},
            {"id": "out", "type": "sink_event", "params": {}, "in": {"event": "$full.event"}},
        ])
        metric, target = ("count_mae", 0.5) if use_case == "pallets" else ("recall", 0.9)
    return [PipelineSpec.model_validate({
        "spec_version": "0.1", "name": f"{use_case}-baseline",
        "inputs": {"source": {"type": source_type, "path": source_path}},
        "blocks": blocks, "eval": {"set": "reviewed-v1", "metric": metric, "target": target},
    })]
