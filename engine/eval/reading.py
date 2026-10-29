"""Measured OCR errors with an explicit policy and bounded edit-distance work."""
from collections.abc import Sequence
from dataclasses import dataclass

NORMALIZATION = "Strip outer whitespace per text region, sort regions case-sensitively, join with newline; words split on whitespace."
MAX_EDIT_CELLS = 2_000_000


def edit_distance(expected: Sequence[str], observed: Sequence[str]) -> int | None:
    """Exact Levenshtein distance, or None when the remaining matrix is too large."""
    start, left_end, right_end = 0, len(expected), len(observed)
    while start < left_end and start < right_end and expected[start] == observed[start]:
        start += 1
    while left_end > start and right_end > start and expected[left_end - 1] == observed[right_end - 1]:
        left_end -= 1
        right_end -= 1
    left, right = expected[start:left_end], observed[start:right_end]
    if not left or not right:
        return max(len(left), len(right))
    if len(left) * len(right) > MAX_EDIT_CELLS:
        return None
    if len(left) > len(right):
        left, right = right, left
    previous = list(range(len(left) + 1))
    for row, value in enumerate(right, 1):
        current = [row]
        for column, other in enumerate(left, 1):
            current.append(min(current[-1] + 1, previous[column] + 1,
                               previous[column - 1] + int(value != other)))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class ReadingErrors:
    exact_match: bool
    expected_characters: int
    character_edits: int | None
    expected_words: int
    word_edits: int | None


def reading_errors(expected: list[str], observed: list[str]) -> ReadingErrors:
    expected_regions, observed_regions = sorted(value.strip() for value in expected), sorted(value.strip() for value in observed)
    truth, prediction = "\n".join(expected_regions), "\n".join(observed_regions)
    truth_words, prediction_words = truth.split(), prediction.split()
    return ReadingErrors(expected_regions == observed_regions, len(truth), edit_distance(truth, prediction),
                         len(truth_words), edit_distance(truth_words, prediction_words))


def error_rate(edits: int | None, reference_units: int) -> float | None:
    if edits is None:
        return None
    if reference_units:
        return edits / reference_units
    return 0.0 if edits == 0 else None
