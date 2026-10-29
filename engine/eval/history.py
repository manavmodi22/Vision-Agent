"""Legacy model-use history never becomes untouched merely after an upgrade."""
from __future__ import annotations

import json
from pathlib import Path

from engine.eval.configuration import project_dataset
from engine.evidence_metadata import relative_image, source_record
from spec.evaluation import EvidenceImage


def legacy_exposures(root: Path, images: list[EvidenceImage]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    legacy = {row.image_path for row in images
              if source_record(root, row.image_path).get("exposure_tracking_version") != "1"}
    for path in legacy:
        result[path] = ["Legacy model-exposure history is unknown; this pre-protocol media is not certified untouched"]
    for row in project_dataset(root).annotations:
        if row.proposal is not None:
            path = relative_image(root, row.image_path)
            result.setdefault(path, []).append("Prior model-generated annotation proposal")
    files = [root / "build.json", root / "project.json"]
    files.extend(sorted((root / "builds").glob("*.json")))
    for history_path in files:
        if not history_path.exists():
            continue
        if history_path.stat().st_size > 16 * 1024 * 1024:
            for image_path in legacy:
                result.setdefault(image_path, []).append("Legacy model history exceeds the inspection bound")
            continue
        value = json.loads(history_path.read_text())
        if not isinstance(value, dict):
            raise ValueError("Saved model-use history is invalid")
        view = value.get("view", value)
        if not isinstance(view, dict):
            raise ValueError("Saved build model-use history is invalid")
        preview = view.get("preview")
        if isinstance(preview, dict):
            for frame in preview.get("frames", []):
                if isinstance(frame, dict) and isinstance(frame.get("image_path"), str):
                    image_path = relative_image(root, frame["image_path"])
                    result.setdefault(image_path, []).append("Prior saved model preview")
        evaluations = view.get("evaluations", [])
        if isinstance(evaluations, list) and any(isinstance(score, dict) and not score.get("protocol_id") for score in evaluations):
            for image_path in legacy:
                result.setdefault(image_path, []).append("Project has pre-protocol model evaluation history")
    return result
