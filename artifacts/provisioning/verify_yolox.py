"""Verify the integrated adapter against the retained official-probe predictions.

The NVIDIA protocol contains published synthetic labels. This program never
imports them into an app or creates review flags, evaluations, or approvals.
Run only after the model has been installed through the reviewed provisioner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import statistics
import time
from pathlib import Path

import numpy as np
from PIL import Image

import engine
from engine.adapters.contracts import DetectionRequest
from engine.adapters.registry import run_inference
from engine.eval.metrics import match_detections
from engine.runtime_identity import source_identity
from spec.models import Detection


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Preserve earlier receipts; choose a new output")
    repo = Path(__file__).resolve().parents[2]
    protocol_path = repo / "artifacts/scene-holdout/protocol.json"
    baseline_path = repo / "artifacts/scene-holdout/yolox-s-onnx-coco.json"
    protocol = json.loads(protocol_path.read_text())
    baseline = json.loads(baseline_path.read_text())
    protocol_hash = sha(protocol_path)
    assert protocol_hash == baseline["protocol_sha256"]
    assert protocol_hash == (protocol_path.parent / "protocol.sha256").read_text().strip()
    package = Path(engine.__file__).resolve().parent.parent
    runtime_hash = source_identity(package)
    request = DetectionRequest(model_id="yolox-s-onnx-coco", classes=["person"],
                               min_conf=protocol["comparison"]["min_conf"])
    prior = {row["image_sha256"]: row for row in baseline["rows"]}
    rows = []
    tp = fp = fn = 0
    errors = []
    identity = None
    started = time.perf_counter()
    for annotation in protocol["annotations"]:
        path = Path(annotation["image_path"])
        assert sha(path) == annotation["image_sha256"]
        with Image.open(path) as image:
            result = run_inference(image, request)
        if identity is None:
            identity = result.identity
        assert result.identity == identity
        assert result.identity.provider == "CPUExecutionProvider"
        expected = [Detection.model_validate(item) for item in annotation["detections"]]
        actual = [Detection(label=d.label, confidence=d.confidence, box=list(d.box))
                  for d in result.detections]
        previous = prior[annotation["image_sha256"]]["predicted"]
        assert len(actual) == len(previous), f"Changed output count on {path.name}"
        for observed, old in zip(actual, previous, strict=True):
            assert observed.label == old["label"]
            assert np.allclose([observed.confidence, *observed.box],
                               [old["confidence"], *old["box"]], atol=1e-6, rtol=0), path.name
        score = match_detections(actual, expected, protocol["comparison"]["matching_iou"])
        tp += score.true_positive
        fp += score.false_positive
        fn += score.false_negative
        errors.append(abs(len(actual) - len(expected)))
        rows.append({"image_path": str(path), "image_sha256": annotation["image_sha256"],
                     "frame_index": annotation["frame_index"], "matches_prior_probe": True,
                     "result": result.model_dump(mode="json")})
        assert sha(path) == annotation["image_sha256"]
    assert source_identity(package) == runtime_hash, "Runtime changed during the verification"
    assert sha(protocol_path) == protocol_hash
    assert identity is not None
    assert identity.artifact_hashes["model.onnx"] == "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
    elapsed = time.perf_counter() - started
    report = {
        "runtime_source_identity": runtime_hash, "package_root": str(package),
        "protocol_sha256": protocol_hash, "prior_probe_sha256": sha(baseline_path),
        "model": request.model_id, "frames": len(rows), "prediction_parity": True,
        "identity": identity.model_dump(mode="json"),
        "diagnostic": {"tp": tp, "fp": fp, "fn": fn,
                       "precision": tp / (tp + fp) if tp + fp else 0,
                       "recall": tp / (tp + fn) if tp + fn else 1,
                       "count_mae": statistics.mean(errors)},
        "elapsed_s": elapsed, "peak_process_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "peak_process_rss_unit": "bytes" if platform.system() == "Darwin" else "KiB",
        "rows": rows, "promotion_eligible": False,
        "scope": "Actual integrated ONNX inference; parity with prior official probe on fixed NVIDIA Warehouse_016 synthetic samples. Published labels remain unreviewed. Not independent real-world acceptance, controlled throughput, or an app approval.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("frames", "prediction_parity", "diagnostic", "elapsed_s")}))


if __name__ == "__main__":
    main()
