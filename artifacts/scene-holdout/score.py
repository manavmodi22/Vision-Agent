"""Score the three fixed-protocol outputs; all scope limitations remain attached."""

import hashlib
import json
from pathlib import Path

from engine.eval.metrics import intersection_over_union, match_detections
from spec.models import Detection

OUT = Path(__file__).resolve().parent
protocol_path = OUT / "protocol.json"
protocol = json.loads(protocol_path.read_text())
protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
receipt = next(f for f in protocol["source_receipts"] if f["path"].endswith("ground_truth.json"))
gtpath = Path(receipt["path"])
assert hashlib.sha256(gtpath.read_bytes()).hexdigest() == receipt["sha256"]
source_gt = json.loads(gtpath.read_text())
camera = protocol["camera"]
summary = {
    "protocol_sha256": protocol_hash,
    "source_scene": protocol["scene"],
    "camera": camera,
    "synthetic": True,
    "frames": len(protocol["annotations"]),
    "expected_person_boxes": sum(len(a["detections"]) for a in protocol["annotations"]),
    "models": [],
    "promotion_eligible": False,
    "scope": "Fixed second synthetic scene, person-only published automatic labels; no app labels, quality approval, or effects changed. Model thresholds were frozen before inference. This is not real-world acceptance.",
    "diagnostic": "Humanoid overlap is post-run failure analysis: unmatched person predictions with IoU>=0.5 against a published FourierGR1T2 box. It is not an additional tuned score or label remapping.",
}
for model in protocol["comparison"]["models"]:
    path = OUT / (model + ".json")
    report = json.loads(path.read_text())
    assert report["protocol_sha256"] == protocol_hash
    tp = fp = fn = overlaps = 0
    errors = []
    rows = []
    for row in report["rows"]:
        expected = [Detection.model_validate(x) for x in row["expected"]]
        predicted = [Detection.model_validate(x) for x in row["predicted"]]
        counts = match_detections(predicted, expected, protocol["comparison"]["matching_iou"])
        tp += counts.true_positive
        fp += counts.false_positive
        fn += counts.false_negative
        error = abs(len(predicted) - len(expected))
        errors.append(error)
        unmatched = set(range(len(expected)))
        extra = []
        for pred in sorted(predicted, key=lambda d: d.confidence, reverse=True):
            candidates = [
                (i, intersection_over_union(pred.box, expected[i].box)) for i in unmatched
            ]
            if candidates:
                index, iou = max(candidates, key=lambda x: x[1])
                if iou >= 0.5:
                    unmatched.remove(index)
                    continue
            extra.append(pred)
        from PIL import Image

        with Image.open(row["image_path"]) as im:
            width, height = im.size
        robots = []
        for item in source_gt[str(row["frame_index"])]:
            label = item.get("object type", item.get("object_type", ""))
            box = item.get("2d bounding box visible", item.get("2d_bounding_box_visible", {})).get(
                camera
            )
            if label == "FourierGR1T2" and box:
                robots.append(
                    [
                        max(0.0, min(1.0, v / (width if i % 2 == 0 else height)))
                        for i, v in enumerate(box)
                    ]
                )
        robot_overlap = sum(
            any(intersection_over_union(p.box, b) >= 0.5 for b in robots) for p in extra
        )
        overlaps += robot_overlap
        rows.append(
            {
                "frame_index": row["frame_index"],
                "image_path": row["image_path"],
                "expected_count": len(expected),
                "predicted_count": len(predicted),
                "true_positive": counts.true_positive,
                "false_positive": counts.false_positive,
                "false_negative": counts.false_negative,
                "count_error": error,
                "false_positives_overlapping_humanoid_robot": robot_overlap,
            }
        )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    summary["models"].append(
        {
            "model": model,
            "prediction_report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "identity": report["identity"],
            "precision": precision,
            "recall": recall,
            "count_mae": sum(errors) / len(errors),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "recall_target": protocol["comparison"]["target_recall"],
            "numeric_recall_target_passed": recall >= protocol["comparison"]["target_recall"],
            "false_positives_overlapping_humanoid_robot": overlaps,
            "total_wall_s": report["total_wall_s"],
            "subsequent_frame_wall_ms_median": report["subsequent_frame_wall_ms_median"],
            "peak_process_rss_raw": report["peak_process_rss_raw"],
            "peak_process_rss_unit": report["peak_process_rss_unit"],
            "failures": sorted(
                rows, key=lambda r: r["false_positive"] + r["false_negative"], reverse=True
            ),
            "limitations": report["limitations"],
        }
    )
output = OUT / "comparison.json"
assert not output.exists()
output.write_text(json.dumps(summary, indent=2) + "\n")
for row in summary["models"]:
    print(
        {
            k: row[k]
            for k in [
                "model",
                "precision",
                "recall",
                "count_mae",
                "numeric_recall_target_passed",
                "false_positives_overlapping_humanoid_robot",
            ]
        }
    )
