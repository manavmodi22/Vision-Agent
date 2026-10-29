"""Exact error counts, aggregate denominators and explicit missing-rate cases."""
from pathlib import Path

import pytest
from PIL import Image

from engine.blocks.reading import VisionReading
from engine.eval import evaluate
from engine.eval.reading import NORMALIZATION, edit_distance, error_rate, reading_errors
from spec.models import Annotation, EvalDataset, EvaluationResult, PipelineSpec


@pytest.mark.parametrize(("truth", "prediction", "distance"), [
    ("ABC-990", "XABC-990Y", 2),
    ("00123", "123", 2),
    ("pallet", "Pallet", 1),
    ("", "EXTRA", 5),
    ("ABC", "", 3),
    ("kitten", "sitting", 3),
    ("倉庫一", "倉庫二", 1),
])
def test_character_distance_preserves_literals_and_insertions(truth: str, prediction: str, distance: int) -> None:
    assert edit_distance(truth, prediction) == distance


def test_normalization_is_explicit_and_preserves_internal_case_and_spacing() -> None:
    result = reading_errors(["  ABC-990 ", "DOCK 4"], ["DOCK 4", "ABC-990"])
    assert result.exact_match and result.character_edits == result.word_edits == 0
    assert not reading_errors(["DOCK 4"], ["dock 4"]).exact_match
    assert not reading_errors(["DOCK  4"], ["DOCK 4"]).exact_match


def test_work_bound_omits_rate_instead_of_truncating_or_fabricating_distance() -> None:
    assert edit_distance("a" * 1500, "b" * 1500) is None
    assert edit_distance("a" * 20000, "a" * 20000) == 0
    assert error_rate(None, 100) is None
    assert error_rate(5, 0) is None
    assert error_rate(0, 0) == 0
    assert error_rate(5, 2) == 2.5  # Insertion-heavy CER/WER can exceed 100 percent.


def test_evaluator_measures_aggregate_reading_rates_and_keeps_exact_match_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.adapters.legacy as executor
    Image.new("RGB", (80, 30), "white").save(tmp_path / "one.png")
    Image.new("RGB", (80, 30), "black").save(tmp_path / "two.png")
    bridge = tmp_path / "bridge"
    bridge.write_bytes(b"synthetic-native-bridge-test")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    def fixture_reading(image: Image.Image) -> VisionReading:
        return VisionReading(texts=["ABC-990" if image.getpixel((0, 0)) == (255, 255, 255) else "A C D"])
    monkeypatch.setattr(executor, "read_native", fixture_reading)
    pipeline = PipelineSpec.model_validate({"name": "Reading metric fixture",
        "inputs": {"source": {"type": "image_folder", "path": "."}},
        "blocks": [{"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "read", "type": "ocr", "in": {"image": "$sample.frame"}}],
        "eval": {"metric": "text_accuracy", "target": .9}})
    labels = EvalDataset(id="reading-errors", annotations=[
        Annotation(image_path="one.png", reviewed=True, expected_texts=["ABC-990"]),
        Annotation(image_path="two.png", reviewed=True, expected_texts=["A B"])])
    result = evaluate(pipeline, labels, tmp_path)
    assert result.character_error_rate == .3
    assert result.word_error_rate == pytest.approx(2 / 3)
    assert result.text_error_counts == {"expected_characters": 10, "character_edits": 3,
                                        "expected_words": 3, "word_edits": 2}
    assert result.text_accuracy == .5 and not result.passed
    assert result.text_normalization == NORMALIZATION
    assert len(result.failures) == 1 and result.failures[0]["observed_texts"] == ["A C D"]


def test_historical_scores_do_not_gain_fabricated_reading_rates() -> None:
    result = EvaluationResult(precision=1, recall=1, count_mae=0, passed=True,
        metric="recall", target=.8, sample_count=10, spec_hash="spec", dataset_hash="data")
    assert result.character_error_rate is None and result.word_error_rate is None
    assert not result.text_error_counts and result.text_normalization is None
