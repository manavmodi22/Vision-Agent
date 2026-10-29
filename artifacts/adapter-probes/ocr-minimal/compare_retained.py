"""Evaluation-only comparison, run after OCR exits; expected strings never enter model process."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
official = json.loads((HERE.parent / "ocr/cpu-feasibility.json").read_text())
direct = json.loads((HERE / "image-only-result.json").read_text())
rows = []
for before, after in zip(official["results"], direct["results"], strict=True):
    assert before["id"] == after["id"]
    observations = after["observations"]
    texts = [o["text"] for o in observations]
    scores = [o["recognition_score"] for o in observations]
    polygons = [o["polygon_pixels"] for o in observations]
    expected = before.get("expected")
    rows.append(
        {
            "id": after["id"],
            "texts": texts,
            "text_equal": texts == before["texts"],
            "scores_exactly_equal": scores == before["raw_recognition_confidences"],
            "max_absolute_score_delta": max(
                (
                    abs(a - b)
                    for a, b in zip(scores, before["raw_recognition_confidences"], strict=True)
                ),
                default=0.0,
            ),
            "polygons_exactly_equal": polygons == before["polygons_pixels"],
            "expected_fixture_literal": expected,
            "fixture_exact": texts == [expected] if expected is not None else None,
            "official_ms": before["inference_ms"],
            "direct_ms": after["total_ms"],
        }
    )
report = {
    "scope": "Implementation parity on four synthetic fixtures and one unlabelled public real crop",
    "representative_accuracy": None,
    "reviewed_annotations_created": False,
    "all_text_score_polygon_parity": all(
        r["text_equal"] and r["scores_exactly_equal"] and r["polygons_exactly_equal"] for r in rows
    ),
    "results": rows,
}
(HERE / "parity.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
