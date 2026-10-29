"""Fixed-protocol standalone measurement; does not create an app evaluation or approval."""

import argparse
import hashlib
import importlib.util
import json
import platform
import resource
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/scene-holdout"
parser = argparse.ArgumentParser()
parser.add_argument(
    "--model", choices=["owlv2-base-patch16", "rtdetr-v2-r18", "yolox-s-onnx-coco"], required=True
)
a = parser.parse_args()
protocol_path = OUT / "protocol.json"
protocol_hash = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
assert protocol_hash == (OUT / "protocol.sha256").read_text().strip()
protocol = json.loads(protocol_path.read_text())
output = OUT / (a.model + ".json")
assert not output.exists(), "Never overwrite benchmark evidence"
for item in protocol["annotations"]:
    assert hashlib.sha256(Path(item["image_path"]).read_bytes()).hexdigest() == item["image_sha256"]
started = time.perf_counter()
if a.model == "yolox-s-onnx-coco":
    spec = importlib.util.spec_from_file_location(
        "isolated_yolox_probe", ROOT / "artifacts/adapter-probes/yolox/probe.py"
    )
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    detector = probe.ProbeDetector()
    identity = {
        "source": "isolated official YOLOX probe",
        "provider": "CPUExecutionProvider",
        "weight_sha256": probe.sha(probe.PROBE / "yolox_s.onnx"),
        "load_ms": detector.load_ms,
        "probe_sha256": hashlib.sha256(
            (ROOT / "artifacts/adapter-probes/yolox/probe.py").read_bytes()
        ).hexdigest(),
    }

    def infer(path):
        detections, _, _ = detector.detect(path, ["person"], protocol["comparison"]["min_conf"])
        return detections
else:
    import torch
    from PIL import Image

    import engine
    from engine.eval.hashes import file_hash
    from engine.models import detect
    from engine.models.manager import owlv2_path, rtdetr_path
    from engine.runtime_identity import source_identity

    package_root = Path(engine.__file__).resolve().parents[1]
    assert package_root.is_relative_to(ROOT / "dist/VisionApp.app"), package_root
    model_path = owlv2_path() if a.model == "owlv2-base-patch16" else rtdetr_path()
    artifact_hashes = {
        p.name: file_hash(p)
        for p in sorted(model_path.iterdir())
        if p.is_file() and p.suffix in {".safetensors", ".json", ".txt"}
    }
    identity = {
        "source": "frozen packaged engine",
        "source_identity": source_identity(package_root),
        "provider": "mps" if torch.backends.mps.is_available() else "cpu",
        "artifact_hashes": artifact_hashes,
        "torch": torch.__version__,
    }

    def infer(path):
        with Image.open(path) as im:
            return [
                x.model_dump(mode="json")
                for x in detect(
                    im.convert("RGB"), a.model, ["person"], protocol["comparison"]["min_conf"]
                )
            ]


rows = []
for item in protocol["annotations"]:
    frame_started = time.perf_counter()
    predictions = infer(Path(item["image_path"]))
    elapsed = (time.perf_counter() - frame_started) * 1000
    rows.append(
        {
            "image_path": item["image_path"],
            "image_sha256": item["image_sha256"],
            "frame_index": item["frame_index"],
            "expected": item["detections"],
            "predicted": predictions,
            "wall_ms": elapsed,
        }
    )
assert hashlib.sha256(protocol_path.read_bytes()).hexdigest() == protocol_hash
if a.model != "yolox-s-onnx-coco":
    assert artifact_hashes == {
        p.name: file_hash(p)
        for p in sorted(model_path.iterdir())
        if p.is_file() and p.suffix in {".safetensors", ".json", ".txt"}
    }, "Model artifacts changed during measurement"
warm = [r["wall_ms"] for r in rows[1:]]
report = {
    "model": a.model,
    "protocol_sha256": protocol_hash,
    "identity": identity,
    "platform": platform.platform(),
    "machine": platform.machine(),
    "rows": rows,
    "total_wall_s": time.perf_counter() - started,
    "first_frame_wall_ms": rows[0]["wall_ms"],
    "subsequent_frame_wall_ms_median": statistics.median(warm),
    "subsequent_frame_wall_ms_max": max(warm),
    "peak_process_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "peak_process_rss_unit": "bytes" if platform.system() == "Darwin" else "KiB",
    "limitations": [
        "Published synthetic annotations remain unreviewed in app",
        "One previously unused source scene/camera, internally correlated frames",
        "Person only; non-person classes including humanoid robots remain negatives",
        "Wall time includes decoding and postprocessing; no controlled throughput or GPU peak memory claim",
        "No recorded events, app evaluation, model promotion or deployment approval",
    ],
}
output.write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps({"model": a.model, "frames": len(rows), "elapsed_s": report["total_wall_s"]}),
    flush=True,
)
