"""Isolated, bounded PP-OCRv5 CPU smoke; no production adapter or accuracy claim."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
import platform
import signal
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
PROBE = ROOT / ".visionapp/adapter-probes/ocr"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deadline(_signum: int, _frame: object) -> None:
    raise TimeoutError("CPU smoke exceeded 180-second total limit")


def setup() -> None:
    for key, value in {
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "PADDLE_PDX_CACHE_HOME": str(PROBE / "cache"),
        "HF_HOME": str(PROBE / "hf-cache"),
        "HF_HUB_OFFLINE": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "VECLIB_MAXIMUM_THREADS": "2",
        "CUDA_VISIBLE_DEVICES": "",
    }.items():
        os.environ[key] = value
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(180)
    for item in json.loads((OUT / "download-receipt.json").read_text()):
        assert sha(Path(item["path"])) == item["sha256"]


def inputs() -> list[dict]:
    from PIL import Image, ImageDraw, ImageFont

    fixtures = ROOT / "artifacts/agent-experience/reading-fixtures"
    rows = [
        {
            "id": "exact-match",
            "path": str(fixtures / "exact-match.png"),
            "expected": "ABC-990",
            "kind": "existing synthetic acceptance fixture",
        },
        {
            "id": "substring-only",
            "path": str(fixtures / "substring-only.png"),
            "expected": "XABC-990Y",
            "kind": "existing synthetic acceptance fixture",
        },
    ]
    folder = OUT / "fixtures"
    folder.mkdir(exist_ok=True)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    font = ImageFont.truetype(str(font_path), 64)
    for identity, text in [("leading-zeros", "001234567890"), ("mixed-case", "AbC-009x")]:
        image = Image.new("RGB", (900, 180), "white")
        ImageDraw.Draw(image).text((45, 48), text, fill="black", font=font)
        path = folder / f"{identity}.png"
        image.save(path)
        rows.append(
            {
                "id": identity,
                "path": str(path),
                "expected": text,
                "kind": "new original synthetic text fixture",
                "font_path": str(font_path),
                "font_sha256": sha(font_path),
            }
        )
    public = (
        Path.home()
        / "Library/Application Support/VisionApp/datasets/nvidia-smartspaces/Warehouse_026-preview.jpg"
    )
    crop_path = folder / "nvidia-real-label-crop.png"
    with Image.open(public) as image:
        crop = (1120, 0, 1920, 600)
        image.crop(crop).save(crop_path)
    rows.append(
        {
            "id": "real-public-label-crop",
            "path": str(crop_path),
            "expected": None,
            "kind": "real public warehouse image crop; no transcript ground truth or human review",
            "source_path": str(public),
            "source_sha256": sha(public),
            "crop_xyxy": crop,
            "dataset": "nvidia/PhysicalAI-SmartSpaces",
            "revision": "2cbe9563cbe9f47f846e5c871ee994572bbbc60e",
            "license": "CC-BY-4.0",
            "attribution": "NVIDIA Physical AI Smart Spaces",
        }
    )
    for row in rows:
        row["sha256"] = sha(Path(row["path"]))
        row["reviewed"] = False
    (OUT / "cpu-inputs.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


def packages() -> list[dict]:
    result = []
    for dist in metadata.distributions():
        files = list(dist.files or [])
        record = next((x for x in files if str(x).endswith(".dist-info/RECORD")), None)
        result.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                "license_files": dist.metadata.get_all("License-File") or [],
                "installed_record_sha256": sha(Path(dist.locate_file(record))) if record else None,
            }
        )
    return sorted(result, key=lambda item: item["name"].lower())


def run() -> None:
    setup()
    started = time.perf_counter()
    import numpy as np
    import paddle
    from paddleocr import PaddleOCR
    from PIL import Image, ImageDraw

    imported_ms = (time.perf_counter() - started) * 1000
    paddle.set_device("cpu")
    assert paddle.get_device() == "cpu" and not paddle.is_compiled_with_cuda()
    cases = inputs()
    initialization = time.perf_counter()
    config = {
        "text_detection_model_name": "PP-OCRv5_mobile_det",
        "text_detection_model_dir": str(PROBE / "models/PP-OCRv5_mobile_det"),
        "text_recognition_model_name": "en_PP-OCRv5_mobile_rec",
        "text_recognition_model_dir": str(PROBE / "models/en_PP-OCRv5_mobile_rec"),
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "device": "cpu",
        "cpu_threads": 2,
        "enable_mkldnn": False,
        "text_recognition_batch_size": 1,
        "text_det_limit_side_len": 960,
        "text_det_limit_type": "max",
        "text_rec_score_thresh": 0.0,
    }
    pipeline = PaddleOCR(**config)
    initialization_ms = (time.perf_counter() - initialization) * 1000
    results = []
    for case in cases:
        path = Path(case["path"])
        before = time.perf_counter()
        predictions = list(pipeline.predict(input=str(path)))
        elapsed = (time.perf_counter() - before) * 1000
        assert len(predictions) == 1
        prediction = predictions[0]
        texts = list(prediction["rec_texts"])
        confidences = [float(x) for x in prediction["rec_scores"]]
        polygons = np.asarray(prediction["rec_polys"]).tolist()
        assert len(texts) == len(confidences) == len(polygons)
        assert all(np.isfinite(x) and 0 <= x <= 1 for x in confidences)
        assert sha(path) == case["sha256"], "Input changed during OCR"
        with Image.open(path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        for poly, text, confidence in zip(polygons, texts, confidences, strict=True):
            draw.line([tuple(point) for point in poly] + [tuple(poly[0])], fill="red", width=2)
            draw.text(tuple(poly[0]), f"{text} ({confidence:.3f})", fill="blue")
        overlay = OUT / f"cpu-{case['id']}-overlay.png"
        image.save(overlay)
        results.append(
            {
                "id": case["id"],
                "input_sha256": case["sha256"],
                "texts": texts,
                "raw_recognition_confidences": confidences,
                "polygons_pixels": polygons,
                "inference_ms": elapsed,
                "expected": case["expected"],
                "exact_preserved": texts == [case["expected"]]
                if case["expected"] is not None
                else None,
                "overlay": str(overlay),
                "reviewed": False,
            }
        )
    checks = {row["id"]: row for row in results}
    report = {
        "status": "actual isolated CPU smoke completed",
        "production_registered": False,
        "representative_accuracy": None,
        "scope": "Four synthetic literal fixtures plus one unlabelled public real crop",
        "device": paddle.get_device(),
        "cuda_compiled": paddle.is_compiled_with_cuda(),
        "network_policy": "Process launched with macOS sandbox-exec deny network*",
        "host": {
            "os": platform.platform(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "config": config,
        "import_ms": imported_ms,
        "initialization_ms": initialization_ms,
        "results": results,
        "checks": {
            "all_synthetic_literals_preserved": all(
                row["exact_preserved"] for row in results if row["expected"] is not None
            ),
            "leading_zeros_preserved": checks["leading-zeros"]["exact_preserved"],
            "mixed_case_preserved": checks["mixed-case"]["exact_preserved"],
            "exact_input_equals_target": checks["exact-match"]["texts"] == ["ABC-990"],
            "substring_input_not_equal_target": checks["substring-only"]["texts"] != ["ABC-990"],
        },
        "script_sha256": sha(Path(__file__)),
        "weights_receipt_sha256": sha(OUT / "download-receipt.json"),
        "input_manifest_sha256": sha(OUT / "cpu-inputs.json"),
        "packages": packages(),
    }
    (OUT / "cpu-feasibility.json").write_text(json.dumps(report, indent=2) + "\n")
    signal.alarm(0)
    print(
        json.dumps(
            {
                "checks": report["checks"],
                "observations": [
                    {"id": r["id"], "texts": r["texts"], "ms": r["inference_ms"]} for r in results
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        (OUT / "cpu-failure.json").write_text(
            json.dumps(
                {"error_type": type(exc).__name__, "message": str(exc), "no_fallback": True},
                indent=2,
            )
            + "\n"
        )
        raise
