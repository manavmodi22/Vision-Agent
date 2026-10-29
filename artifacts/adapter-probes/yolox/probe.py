"""Isolated official YOLOX-s ONNX CPU feasibility; no production registration."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import statistics
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / ".visionapp/adapter-probes/yolox"
OUT = Path(__file__).parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PROVENANCE = json.loads((OUT / "provenance.json").read_text())
assert sha(PROBE / "yolox_s.onnx") == PROVENANCE["checkpoint"]["sha256"]
for source_file in PROVENANCE["source_files"]:
    assert sha(PROBE / "upstream" / source_file["path"]) == source_file["sha256"]


module_spec = importlib.util.spec_from_file_location(
    "official_yolox_demo_utils", PROBE / "upstream/yolox/utils/demo_utils.py"
)
assert module_spec and module_spec.loader
upstream = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(upstream)
tree = ast.parse((PROBE / "upstream/yolox/data/datasets/coco_classes.py").read_text())
CLASSES = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign))
assert (
    len(CLASSES) == 80
    and CLASSES[0] == "person"
    and "forklift" not in CLASSES
    and "pallet" not in CLASSES
)


class ProbeDetector:
    def __init__(self) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        started = time.perf_counter()
        self.session = ort.InferenceSession(
            str(PROBE / "yolox_s.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.load_ms = (time.perf_counter() - started) * 1000
        assert self.session.get_providers() == ["CPUExecutionProvider"]
        assert self.session.get_inputs()[0].shape == [1, 3, 640, 640]

    def detect(
        self, path: Path, classes: list[str], confidence: float = 0.15
    ) -> tuple[list[dict], float, float]:
        if any(name not in CLASSES for name in classes):
            raise ValueError("Unsupported closed-vocabulary class; no remapping or fallback")
        started = time.perf_counter()
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError("Unreadable image")
        height, width = image.shape[:2]
        ratio = min(640 / height, 640 / width)
        # Same raw BGR, top-left 114 padding and bilinear resize as upstream preproc.
        padded = np.full((640, 640, 3), 114, dtype=np.uint8)
        padded[: int(height * ratio), : int(width * ratio)] = cv2.resize(
            image, (int(width * ratio), int(height * ratio)), interpolation=cv2.INTER_LINEAR
        )
        tensor = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
        inference_start = time.perf_counter()
        output = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0]
        inference_ms = (time.perf_counter() - inference_start) * 1000
        assert output.shape == (1, 8400, 85) and np.isfinite(output).all()
        prediction = upstream.demo_postprocess(output, (640, 640))[0]
        scores = prediction[:, 4:5] * prediction[:, 5:]
        boxes = (
            np.concatenate(
                (
                    prediction[:, :2] - prediction[:, 2:4] / 2,
                    prediction[:, :2] + prediction[:, 2:4] / 2,
                ),
                axis=1,
            )
            / ratio
        )
        detections = upstream.multiclass_nms(boxes, scores, nms_thr=0.45, score_thr=confidence)
        result = []
        if detections is not None:
            for x0, y0, x1, y1, score, class_id in detections:
                label = CLASSES[int(class_id)]
                if label not in classes:
                    continue
                box = np.clip(
                    np.array([x0 / width, y0 / height, x1 / width, y1 / height]), 0, 1
                ).tolist()
                if box[0] < box[2] and box[1] < box[3]:
                    result.append({"label": label, "confidence": float(score), "box": box})
        return (
            sorted(result, key=lambda x: -x["confidence"]),
            inference_ms,
            (time.perf_counter() - started) * 1000,
        )


def iou(a: list[float], b: list[float]) -> float:
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0


def main() -> None:
    detector = ProbeDetector()
    public = (
        Path.home()
        / "Library/Application Support/VisionApp/datasets/nvidia-smartspaces/Warehouse_026-preview.jpg"
    )
    public_sha = sha(public)
    predictions, cold_ms, total_ms = detector.detect(public, ["person"])
    timings = [detector.detect(public, ["person"])[1] for _ in range(5)]
    # Contract check: unsupported requested labels are rejected before inference.
    for unsupported in ("forklift", "pallet"):
        try:
            detector.detect(public, [unsupported])
            raise AssertionError("Unsupported label was accepted")
        except ValueError:
            pass
    overlay = cv2.imread(str(public))
    height, width = overlay.shape[:2]
    for det in predictions:
        x0, y0, x1, y1 = det["box"]
        cv2.rectangle(
            overlay,
            (int(x0 * width), int(y0 * height)),
            (int(x1 * width), int(y1 * height)),
            (0, 200, 255),
            2,
        )
        cv2.putText(
            overlay,
            f"person {det['confidence']:.2f}",
            (int(x0 * width), max(15, int(y0 * height) - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 200, 255),
            1,
        )
    cv2.imwrite(str(OUT / "real-person-overlay.jpg"), overlay)
    report = {
        "model": "YOLOX-s official ONNX 0.1.1rc0",
        "production_registered": False,
        "providers": detector.session.get_providers(),
        "available_providers": ort.get_available_providers(),
        "host": {"os": platform.platform(), "architecture": platform.machine()},
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("onnxruntime", "numpy", "opencv-python-headless", "pillow")
        },
        "model_sha256": sha(PROBE / "yolox_s.onnx"),
        "model_bytes": (PROBE / "yolox_s.onnx").stat().st_size,
        "input": [1, 3, 640, 640],
        "output": [1, 8400, 85],
        "score_threshold": 0.15,
        "nms_iou": 0.45,
        "vocabulary": list(CLASSES),
        "reported_classes": ["person"],
        "unsupported_rejected": ["forklift", "pallet"],
        "real_image": {
            "path": str(public),
            "sha256": public_sha,
            "label_status": "Unlabelled public real footage; no accuracy score",
            "detections": predictions,
        },
        "timing_ms": {
            "load": detector.load_ms,
            "first_inference": cold_ms,
            "first_decode_to_results": total_ms,
            "warm_inference_runs": timings,
            "warm_inference_median": statistics.median(timings),
            "threads": 4,
        },
        "limitations": [
            "Single-image timing is not sustained throughput",
            "No production adapter or deployment approval",
            "No forklift/pallet mapping",
        ],
    }
    source = Path.home() / "Library/Application Support/VisionApp/projects/a009404fe6c546ec"
    annotations_path = source / "annotations.json"
    annotations_sha = sha(annotations_path)
    data = json.loads(annotations_path.read_text())
    rows = []
    tp = fp = fn = 0
    count_errors = []
    for annotation in data["annotations"]:
        path = Path(annotation["image_path"])
        image_sha = sha(path)
        actual, elapsed, _ = detector.detect(path, ["person"])
        assert sha(path) == image_sha, "Source image changed during inference"
        expected = [item["box"] for item in annotation["detections"] if item["label"] == "person"]
        unmatched = set(range(len(expected)))
        matched = 0
        for detection in actual:
            candidates = [(iou(detection["box"], expected[index]), index) for index in unmatched]
            overlap, index = max(candidates, default=(0, -1))
            if overlap >= 0.5:
                unmatched.remove(index)
                matched += 1
        tp += matched
        fp += len(actual) - matched
        fn += len(expected) - matched
        count_errors.append(abs(len(actual) - len(expected)))
        rows.append(
            {
                "path": str(path),
                "sha256": image_sha,
                "expected_persons": len(expected),
                "predicted_persons": len(actual),
                "tp": matched,
                "fp": len(actual) - matched,
                "fn": len(expected) - matched,
                "inference_ms": elapsed,
                "predictions": actual,
            }
        )
    report["synthetic_person_snapshot"] = {
        "frames": len(rows),
        "annotations_sha256": annotations_sha,
        "label_status": "Imported published synthetic labels, not human-reviewed; project flags unchanged",
        "dataset": json.loads((source / "source-provenance.json").read_text()),
        "iou": 0.5,
        "precision": tp / (tp + fp) if tp + fp else 0,
        "recall": tp / (tp + fn) if tp + fn else 0,
        "count_mae": statistics.mean(count_errors),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "rows": rows,
        "comparison": None,
        "limitation": "One correlated synthetic camera; cannot compare to historical two-class OWLv2 aggregate.",
    }
    assert sha(annotations_path) == annotations_sha, "Annotations changed during scoring"
    assert sha(public) == public_sha, "Real image changed during inference"
    assert sha(PROBE / "yolox_s.onnx") == PROVENANCE["checkpoint"]["sha256"]
    report["probe_script_sha256"] = sha(Path(__file__))
    report["input_integrity_verified"] = True
    (OUT / "feasibility.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "real_person_predictions": len(predictions),
                "warm_median_ms": statistics.median(timings),
                "synthetic_person_precision": report["synthetic_person_snapshot"]["precision"],
                "synthetic_person_recall": report["synthetic_person_snapshot"]["recall"],
            }
        )
    )


if __name__ == "__main__":
    main()
