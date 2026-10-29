"""Software contract checks against pinned upstream operations; no accuracy claim."""
from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image

from engine.models.manager import ModelUnavailable, trained_classes
from engine.models.yolox_config import COCO_CLASSES, MODEL_ID
from engine.models.yolox_ops import FloatArray, _nms, postprocess, preprocess


def raw_prediction() -> FloatArray:
    return np.zeros((1, 8400, 85), dtype=np.float32)


def test_input_is_raw_bgr_chw_top_left_114_padding_without_mutating_image() -> None:
    image = Image.new("RGB", (2, 1), (250, 100, 5))
    before = image.tobytes()
    tensor, ratio = preprocess(image)
    assert tensor.shape == (1, 3, 640, 640) and tensor.dtype == np.float32
    assert tensor.flags.c_contiguous and ratio == 320
    np.testing.assert_array_equal(tensor[0, :, 0, 0], [5, 100, 250])
    np.testing.assert_array_equal(tensor[0, :, 319, 639], [5, 100, 250])
    np.testing.assert_array_equal(tensor[0, :, 320, 0], [114, 114, 114])
    assert image.tobytes() == before


def test_closed_vocabulary_is_advertised_even_without_installed_weights() -> None:
    assert len(COCO_CLASSES) == len(set(COCO_CLASSES)) == 80
    assert trained_classes(MODEL_ID) == list(COCO_CLASSES)
    assert COCO_CLASSES[0] == "person" and COCO_CLASSES[7] == "truck"
    assert "forklift" not in COCO_CLASSES and "pallet" not in COCO_CLASSES


@pytest.mark.parametrize(("index", "stride"), [(81, 8), (6441, 16), (8021, 32)])
def test_each_grid_scale_decodes_into_original_image_space(index: int, stride: int) -> None:
    raw = raw_prediction()
    raw[0, index, :4] = [.5, .5, math.log(2), math.log(2)]
    raw[0, index, 4:6] = [.8, .5]
    before = raw.copy()
    # Grid x=1,y=1 at each scale; inverse resize restores 320x320 source.
    detections = postprocess(raw, (320, 320), 2, ["person"], .3)
    assert len(detections) == 1
    assert detections[0].confidence == pytest.approx(.4)
    assert detections[0].box == pytest.approx([.5 * stride / 640, .5 * stride / 640,
                                              2.5 * stride / 640, 2.5 * stride / 640])
    np.testing.assert_array_equal(raw, before)


def test_other_class_can_suppress_requested_class_before_class_filtering() -> None:
    raw = raw_prediction()
    # Two identical boxes with differing raw offsets for adjacent grid cells.
    raw[0, 0, :4] = [10, 10, 2, 2]
    raw[0, 1, :4] = [9, 10, 2, 2]
    raw[0, :2, 4] = 1
    raw[0, 0, 5] = .8  # person
    raw[0, 1, 7] = .9  # car
    assert postprocess(raw, (640, 640), 1, ["person"], .2) == []
    both = postprocess(raw, (640, 640), 1, ["person", "car"], .2)
    assert len(both) == 1 and both[0].label == "car"


def test_nms_preserves_inclusive_pixel_iou() -> None:
    # Inclusive-pixel IoU=.5 -> suppressed at .45; exclusive IoU=1/3 would keep both.
    boxes = np.array([[0, 0, 2, 2], [1, 0, 3, 2]], dtype=np.float32)
    assert _nms(boxes, np.array([.9, .8], dtype=np.float32)) == [0]


def test_threshold_is_strict_and_clipping_removes_degenerate_boxes() -> None:
    raw = raw_prediction()
    raw[0, 0, 4:6] = [1, .5]
    assert postprocess(raw, (10, 10), 1, ["person"], .5) == []
    detection = postprocess(raw, (10, 10), 1, ["person"], .49)[0]
    assert detection.box == [0, 0, .4, .4]
    raw[0, 0, :2] = [-100, -100]
    assert postprocess(raw, (10, 10), 1, ["person"], .49) == []


@pytest.mark.parametrize("problem", ["nan", "inf", "score", "negative_score", "exp_overflow", "shape", "dtype"])
def test_invalid_outputs_fail_instead_of_becoming_plausible_detections(problem: str) -> None:
    raw = raw_prediction()
    if problem == "shape":
        raw = raw[:, :-1]
    elif problem == "dtype":
        with pytest.raises(ModelUnavailable, match="float32"):
            postprocess(raw.astype(np.float64), (640, 640), 1, ["person"], .2)  # type: ignore[arg-type]
        return
    else:
        raw[0, 0, 2 if problem == "exp_overflow" else 5] = {
            "nan": math.nan, "inf": math.inf, "score": 1.1, "negative_score": -.1,
            "exp_overflow": 1000,
        }[problem]
    with pytest.raises(ModelUnavailable):
        postprocess(raw, (640, 640), 1, ["person"], .2)


def test_extreme_aspect_ratio_fails_clearly() -> None:
    with pytest.raises(ModelUnavailable, match="empty resized dimension"):
        preprocess(Image.new("RGB", (1, 32768)))
