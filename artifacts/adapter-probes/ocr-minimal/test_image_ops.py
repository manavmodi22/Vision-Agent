"""Deterministic contract checks; no model inference or expected-answer hints."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from direct_ocr import PINNED_FILES, verify_files
from image_ops import crop_quad, decode_ctc, detection_boxes, detection_input, recognition_input
from run_offline import launch


class ImageContractTests(unittest.TestCase):
    def test_ctc_preserves_case_and_separated_repeated_zeros(self):
        characters = ["blank", "A", "b", "C", "-", "0", "9", "x", " "]
        ids = [1, 1, 0, 2, 3, 4, 5, 5, 0, 5, 6, 7, 0]
        logits = np.eye(len(characters), dtype=np.float32)[ids][None]
        self.assertEqual(decode_ctc(logits, characters), ("AbC-009x", 1.0))

    def test_blank_has_measured_zero_score(self):
        output = np.zeros((1, 4, 2), np.float32)
        output[:, :, 0] = 1
        self.assertEqual(decode_ctc(output, ["blank", "A"]), ("", 0.0))

    def test_invalid_recognition_rejected(self):
        for output in (np.zeros((2, 2)), np.full((1, 1, 2), np.nan), np.full((1, 1, 2), 1.1)):
            with self.subTest(shape=output.shape), self.assertRaises(ValueError):
                decode_ctc(output, ["blank", "A"])

    def test_invalid_detection_rejected(self):
        for output in (np.zeros((1, 2)), np.full((1, 1, 2, 2), np.inf), np.full((1, 1, 2, 2), -1)):
            with self.subTest(shape=output.shape), self.assertRaises(ValueError):
                detection_boxes(output, 32, 32)

    def test_detection_coordinates_and_corresponding_scores(self):
        output = np.zeros((1, 1, 100, 100), np.float32)
        output[0, 0, 15:25, 10:25] = 0.9
        output[0, 0, 65:75, 60:75] = 0.7
        result = detection_boxes(output, 200, 300)
        self.assertEqual(len(result), 2)
        self.assertGreater(result[0][1], result[1][1])
        for quad, score in result:
            self.assertEqual(quad.shape, (4, 2))
            self.assertTrue(np.all(quad >= 0))
            self.assertTrue(np.all(quad[:, 0] <= 300))
            self.assertTrue(np.all(quad[:, 1] <= 200))
            self.assertGreaterEqual(score, 0.6)

    def test_empty_detection(self):
        self.assertEqual(detection_boxes(np.zeros((1, 1, 32, 32), np.float32), 32, 32), [])

    def test_detector_max_side_and_float32(self):
        image = np.full((1000, 2000, 3), 255, np.uint8)
        data = detection_input(image)
        self.assertEqual(data.shape, (1, 3, 480, 960))
        self.assertEqual(data.dtype, np.float32)
        self.assertTrue(np.isfinite(data).all())

    def test_tiny_input_padding(self):
        self.assertEqual(detection_input(np.zeros((4, 4, 3), np.uint8)).shape, (1, 3, 32, 32))

    def test_detector_rejects_out_of_bound_input(self):
        with self.assertRaisesRegex(ValueError, "bounds"):
            detection_input(np.zeros((1, 8193, 3), np.uint8))

    def test_batch_rejects_expected_answer_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = root / "inputs.json"
            paths.write_text(json.dumps([{"path": "image.png", "expected": "answer"}]))
            with self.assertRaisesRegex(ValueError, "image path strings"):
                launch(root / "result.json", paths)

    def test_batch_rejects_empty_and_excessive_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = root / "inputs.json"
            for rows in ([], ["image.png"] * 501):
                paths.write_text(json.dumps(rows))
                with self.assertRaisesRegex(ValueError, "1–500"):
                    launch(root / "result.json", paths)

    def test_recognizer_padding_is_zero_and_width_bounded(self):
        data = recognition_input(np.full((48, 20, 3), 255, np.uint8))
        self.assertEqual(data.shape, (1, 3, 48, 320))
        self.assertTrue(np.all(data[:, :, :, :20] == 1))
        self.assertTrue(np.all(data[:, :, :, 20:] == 0))
        self.assertEqual(
            recognition_input(np.zeros((1, 4000, 3), np.uint8)).shape, (1, 3, 48, 3200)
        )

    def test_crop_is_oriented_by_geometry_only(self):
        image = np.zeros((100, 100, 3), np.uint8)
        quad = np.array([[20, 10], [40, 10], [40, 90], [20, 90]])
        crop = crop_quad(image, quad)
        self.assertEqual(crop.shape[:2], (20, 80))

    def test_missing_or_changed_model_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                verify_files(root)
            name = next(iter(PINNED_FILES))
            (root / name).mkdir()
            (root / name / "config.json").write_text(json.dumps({"wrong": True}))
            with self.assertRaisesRegex(ValueError, "mismatch"):
                verify_files(root)


if __name__ == "__main__":
    unittest.main()
