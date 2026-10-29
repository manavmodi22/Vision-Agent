"""Label-aware one-to-one bounding box matching and count metrics."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from spec.models import Detection


def intersection_over_union(left: list[float], right: list[float]) -> float:
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1]))
    union = ((left[2] - left[0]) * (left[3] - left[1])
             + (right[2] - right[0]) * (right[3] - right[1]) - intersection)
    return intersection / union if union else 0


@dataclass(frozen=True)
class MatchCounts:
    true_positive: int
    false_positive: int
    false_negative: int


def match_detections(predicted: list[Detection], actual: list[Detection], iou_threshold: float = 0.5) -> MatchCounts:
    unmatched = set(range(len(actual)))
    matched = 0
    for prediction in sorted(predicted, key=lambda item: item.confidence, reverse=True):
        candidates = [(index, intersection_over_union(prediction.box, truth.box))
                      for index, truth in enumerate(actual)
                      if index in unmatched and prediction.label == truth.label]
        if candidates:
            best, score = max(candidates, key=lambda item: item[1])
            if score >= iou_threshold:
                unmatched.remove(best)
                matched += 1
    return MatchCounts(matched, len(predicted) - matched, len(actual) - matched)


def count_errors(predicted: list[Detection], actual: list[Detection], zone_ids: list[str]) -> list[float]:
    if zone_ids or any(d.zone is not None for d in actual):
        expected = Counter(d.zone or "unassigned" for d in actual)
        observed = Counter(d.zone or "unassigned" for d in predicted)
        keys = set(zone_ids) | set(expected) | set(observed)
        return [float(abs(observed[key] - expected[key])) for key in sorted(keys)]
    return [float(abs(len(predicted) - len(actual)))]
