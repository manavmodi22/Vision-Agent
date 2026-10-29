"""Text label contracts preserve literal content and reject unusable shapes."""
import pytest
from pydantic import ValidationError

from spec.models import Annotation
from spec.text_annotations import TextRegion, TextRegionSeed


def region(transcript: str | None = "X") -> TextRegion:
    return TextRegion(id="r1", polygon=[(.1, .2), (.8, .15), (.75, .5), (.15, .55)], transcript=transcript)


@pytest.mark.parametrize("polygon", [
    [(0., 0.), (1., 1.), (1., 0.), (0., 1.)],
    [(0., 0.), (1., 0.), (.3, .2), (0., 1.)],
    [(0., 0.), (.5, 0.), (1., 0.), (0., 1.)],
    [(0., 0.), (1., 0.), (1., 0.), (0., 1.)],
    [(-.1, 0.), (1., 0.), (1., 1.), (0., 1.)],
    [(float("nan"), 0.), (1., 0.), (1., 1.), (0., 1.)],
])
def test_bad_annotation_quadrilateral_is_rejected(polygon: list[tuple[float, float]]) -> None:
    with pytest.raises(ValidationError):
        TextRegion(id="r1", polygon=polygon)


def test_skewed_shape_envelope_and_both_winding_orders() -> None:
    value = region()
    assert value.box == (.1, .15, .8, .55)
    reverse = TextRegion(id="reverse", polygon=list(reversed(value.polygon)))
    assert reverse.box == value.box
    with pytest.raises(ValidationError, match="envelope"):
        TextRegion(id="wrong", polygon=value.polygon, box=(.1, .1, .8, .8))


def test_legacy_manual_labels_and_region_projection_are_distinct() -> None:
    legacy = Annotation.model_validate({"image_path": "frame.png", "reviewed": True, "expected_texts": ["KEEP"]})
    assert legacy.expected_text_source == "manual" and legacy.text_regions == []
    rows = [region("Х"), region("X").model_copy(update={"id": "r2"}), region("X").model_copy(update={"id": "r3"})]
    manual = Annotation(image_path="frame.png", text_regions=rows, expected_texts=["KEEP"])
    projected = Annotation(image_path="frame.png", text_regions=rows, expected_texts=["discarded"], expected_text_source="regions")
    assert manual.expected_texts == ["KEEP"]
    assert projected.expected_texts == ["Х", "X", "X"]
    assert Annotation.model_validate_json(projected.model_dump_json()) == projected


@pytest.mark.parametrize("transcript", [None, "", " \t"])
def test_draft_transcript_cannot_be_reviewed(transcript: str | None) -> None:
    draft = Annotation(image_path="frame.png", text_regions=[region(transcript)])
    assert not draft.reviewed
    with pytest.raises(ValidationError, match="Complete every"):
        Annotation(image_path="frame.png", text_regions=[region(transcript)], reviewed=True)


def test_region_ids_are_unique_and_review_preserves_whitespace() -> None:
    with pytest.raises(ValidationError, match="unique"):
        Annotation(image_path="frame.png", text_regions=[region(), region()])
    annotation = Annotation(image_path="frame.png", text_regions=[region(" A  B ")], reviewed=True, expected_text_source="regions")
    assert annotation.expected_texts == [" A  B "]


def test_seed_keeps_native_observation_without_promoting_its_score() -> None:
    seed = TextRegionSeed.model_validate({"model_id": "apple-vision", "adapter_id": "apple-vision", "identity_hash": "a" * 64,
        "block_id": "read", "observation_index": 0, "image_sha256": "b" * 64, "created_at": "2026-10-29T04:00:00Z",
        "input_to_frame": [.2, .3, .4, .5], "observation": {"text": "Х", "kind": "ocr", "box": [.1, .1, .8, .8], "confidence": .7}})
    annotated = region("X").model_copy(update={"seed": seed})
    assert annotated.transcript == "X" and annotated.seed is not None
    assert annotated.seed.observation.text == "Х" and annotated.seed.observation.confidence == .7
    assert "confidence" not in annotated.model_dump()
    invalid = seed.model_dump(mode="json")
    invalid["input_to_frame"] = [.9, .3, .4, .5]
    with pytest.raises(ValidationError, match="transform"):
        TextRegionSeed.model_validate(invalid)
