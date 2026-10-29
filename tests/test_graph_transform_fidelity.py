"""Initial graph transforms must operate on the described branch in stated order."""
import pytest

from agent.graph_language import branch_request, clauses_for_branch
from agent.graph_transforms import validate_transforms
from spec.authoring import GraphCandidate


def graph(*, ocr: list[tuple[str, object]] | None = None,
          barcode: list[tuple[str, object]] | None = None, detector: bool = False) -> GraphCandidate:
    nodes: list[dict[str, object]] = [{"type": "frame_sample", "id": "sample", "fps": 2}]
    for kind, operations in [("ocr", ocr), ("barcode", barcode), ("detect", [] if detector else None)]:
        if operations is None:
            continue
        image = "$sample.frame"
        for index, (operation, value) in enumerate(operations):
            identifier = f"{kind}_{operation}_{index}"
            params = {"box": value} if operation == "crop" else {"width": value[0], "height": value[1]}
            nodes.append({"id": identifier, "type": operation, "image": image, **params})
            image = f"${identifier}.image"
        extra = {"classes": ["pallet"], "min_confidence": .5} if kind == "detect" else {}
        nodes.append({"id": kind + "_task", "type": kind, "image": image,
            "model_capability_id": "model.test", "model_reason": "Typed software proposal", **extra})
    return GraphCandidate.model_validate({"name": "Scoped transforms", "nodes": nodes,
        "metric": "recall" if detector else "text_accuracy", "target": .9})


LEFT = ("crop", [0, 0, .5, 1])
RIGHT = ("crop", [.5, 0, 1, 1])
SIZE = ("resize", (1200, 800))


@pytest.mark.parametrize("prompt", [
    "Read printed text from the left half; decode barcodes from the full frame.",
    "OCR from the left half and barcodes from the full frame.",
    "Read OCR from the left half, but leave barcode reading uncropped.",
    "Use OCR on the left half while barcodes use the entire image.",
    "OCR on the left half and barcodes on the whole image.",
    "OCR on the left half of the full frame; barcodes on the entire frame.",
])
def test_transform_binds_to_correct_naturally_named_branch(prompt: str) -> None:
    validate_transforms(graph(ocr=[LEFT], barcode=[]), prompt)
    for wrong in [graph(ocr=[], barcode=[LEFT]), graph(ocr=[LEFT], barcode=[LEFT]), graph(ocr=[], barcode=[])]:
        with pytest.raises(ValueError):
            validate_transforms(wrong, prompt)


def test_two_different_requested_crops_cannot_both_be_omitted_or_swapped() -> None:
    prompt = "Read OCR from the left half and barcodes from the right half"
    validate_transforms(graph(ocr=[LEFT], barcode=[RIGHT]), prompt)
    for wrong in [graph(ocr=[], barcode=[]), graph(ocr=[RIGHT], barcode=[LEFT]), graph(ocr=[LEFT], barcode=[LEFT])]:
        with pytest.raises(ValueError):
            validate_transforms(wrong, prompt)


@pytest.mark.parametrize("prompt", [
    "Crop the left half then resize to 1200x800 before OCR",
    "Crop the left half before resizing to 1200 by 800 for printed text",
    "Resize to 1200 × 800 after cropping the left half before OCR",
    "Read printed text from the left half. Resize to 1200 by 800 pixels.",
    "Crop the left half, then resize width1200 and height800 for OCR",
])
def test_explicit_crop_then_resize_preserves_chain_order(prompt: str) -> None:
    validate_transforms(graph(ocr=[LEFT, SIZE]), prompt)
    with pytest.raises(ValueError, match="order"):
        validate_transforms(graph(ocr=[SIZE, LEFT]), prompt)


@pytest.mark.parametrize("prompt", [
    "Resize to 1200x800 then crop the left half before OCR",
    "Crop the left half after resizing to 1200x800 for OCR",
])
def test_reverse_order_is_distinct_and_supported(prompt: str) -> None:
    validate_transforms(graph(ocr=[SIZE, LEFT]), prompt)
    with pytest.raises(ValueError):
        validate_transforms(graph(ocr=[LEFT, SIZE]), prompt)


def test_normalized_coordinates_and_width_height_are_exact_and_branch_local() -> None:
    prompt = "OCR: crop [0.1, 0.2, 0.6, 0.8], then resize width1200 and height400; read barcodes from the full frame"
    expected = [("crop", [.1, .2, .6, .8]), ("resize", (1200, 400))]
    validate_transforms(graph(ocr=expected, barcode=[]), prompt)
    for changed in [[("crop", [.1, .2, .7, .8]), ("resize", (1200, 400))],
                    [("crop", [.1, .2, .6, .8]), ("resize", (400, 1200))]]:
        with pytest.raises(ValueError):
            validate_transforms(graph(ocr=changed, barcode=[]), prompt)


def test_natural_branch_specific_pixel_dimensions_are_not_assigned_to_other_reader() -> None:
    prompt = "OCR at width1200 and height800; barcodes at 640x480"
    validate_transforms(graph(ocr=[SIZE], barcode=[("resize", (640, 480))]), prompt)
    with pytest.raises(ValueError):
        validate_transforms(graph(ocr=[("resize", (640, 480))], barcode=[SIZE]), prompt)


def test_common_explicit_stage_may_feed_both_readers() -> None:
    prompt = "Crop to the left half then resize to 1200x800 for OCR and barcodes"
    validate_transforms(graph(ocr=[LEFT, SIZE], barcode=[LEFT, SIZE]), prompt)
    with pytest.raises(ValueError):
        validate_transforms(graph(ocr=[LEFT, SIZE], barcode=[]), prompt)


@pytest.mark.parametrize("operations,prompt", [
    ([LEFT], "Read printed text"), ([SIZE], "Read printed text"),
    ([LEFT], "Read OCR from the full frame; do not crop"),
    ([SIZE], "Read OCR without resizing"),
    ([SIZE], "Use OCR at original resolution"),
    ([LEFT], "Do not crop the left half; read OCR from the whole frame"),
    ([LEFT], 'Read OCR and compare to "crop the left half"'),
    ([SIZE], 'Read OCR and compare to "resize1200x800"'),
    ([LEFT, LEFT], "Crop the left half for OCR"),
    ([SIZE, SIZE], "Resize to 1200x800 for OCR"),
])
def test_unrequested_forbidden_or_extra_transforms_reject(operations: list[tuple[str, object]], prompt: str) -> None:
    with pytest.raises(ValueError):
        validate_transforms(graph(ocr=operations), prompt)


@pytest.mark.parametrize("prompt", ["Crop the label before OCR", "Resize for OCR", "Resize width1200 for OCR",
    "Crop the left half of each pallet before OCR", "Resize to 1200x800 and preserve aspect ratio for OCR"])
def test_unsupported_or_underdefined_geometry_needs_clarification(prompt: str) -> None:
    with pytest.raises(ValueError):
        validate_transforms(graph(ocr=[]), prompt)


def test_unscoped_transform_with_multiple_consumers_needs_clarification() -> None:
    with pytest.raises(ValueError, match="branch is ambiguous"):
        validate_transforms(graph(ocr=[LEFT], barcode=[]), "Crop the left half. Read OCR and barcodes.")


def test_detector_branch_preserved_when_reader_is_cropped() -> None:
    validate_transforms(graph(ocr=[LEFT], detector=True), "Detect pallets on the full frame and read printed text from the left half")


def test_branch_request_preserves_literals_and_comparison_scope() -> None:
    prompt = 'Read OCR from the left half and compare exactly to "ABC-990"; decode barcodes on the full frame without comparison'
    assert '"ABC-990"' in branch_request(prompt, "ocr")
    assert '"ABC-990"' not in branch_request(prompt, "barcode")
    assert "without comparison" in branch_request(prompt, "barcode")


def test_common_comparison_stays_shared_for_caller_ambiguity_guard() -> None:
    prompt = 'Read OCR and barcodes. Compare recognized text exactly to "ABC-990"'
    ocr, barcode = clauses_for_branch(prompt, "ocr"), clauses_for_branch(prompt, "barcode")
    assert any('"ABC-990"' in clause for clause in set(ocr) & set(barcode))
    prompt = 'Detect pallets and read printed text. Compare recognized text exactly to "ABC-990"'
    assert '"ABC-990"' in branch_request(prompt, "ocr")


@pytest.mark.parametrize("negative", ["Do not crop or resize", "Neither crop nor resize", "No cropping or resizing",
    "Do not resize or crop", "Without resizing or cropping"])
def test_coordinated_negation_does_not_request_geometry(negative: str) -> None:
    prompt = "Read OCR and barcodes. " + negative
    validate_transforms(graph(ocr=[], barcode=[]), prompt)
    for wrong in [graph(ocr=[LEFT], barcode=[]), graph(ocr=[], barcode=[SIZE])]:
        with pytest.raises(ValueError):
            validate_transforms(wrong, prompt)


def test_half_repeated_as_exact_coordinates_is_one_crop() -> None:
    prompt = "Read printed text from the left half: crop normalized [0,0,0.5,1], then resize that crop to width1200 and height400 before OCR"
    validate_transforms(graph(ocr=[LEFT, ("resize", (1200, 400))]), prompt)
    validate_transforms(graph(ocr=[LEFT, ("resize", (1200, 400))]),
                        "Crop the left half for OCR. Resize that crop to width1200 and height400.")
