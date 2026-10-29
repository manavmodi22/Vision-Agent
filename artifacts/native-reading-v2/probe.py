"""Actual bounded Apple Vision protocol probe; no models or user projects changed."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.blocks.reading import NativeVisionReading, VisionReading  # noqa: E402

OUT = Path(__file__).resolve().parent
BINARY = ROOT / "app/.build/debug/VisionApp"


def main() -> None:
    exact = ROOT / "artifacts/agent-experience/reading-fixtures/exact-match.png"
    base = Image.open(exact).convert("RGB")
    exif = Image.Exif()
    exif[274] = 6
    base.transpose(Image.Transpose.ROTATE_90).save(OUT / "rotated-exif.jpg", exif=exif, quality=98)
    exif[274] = 2
    ImageOps.mirror(base).save(OUT / "mirrored-exif.jpg", exif=exif, quality=98)
    base.rotate(8, expand=True, fillcolor="white").save(OUT / "skewed.png")
    qr = cv2.QRCodeEncoder_create().encode("NATIVE-READING-V2-QR")
    ImageOps.expand(Image.fromarray(qr), border=4, fill="white").resize((480, 480), Image.Resampling.NEAREST).save(OUT / "qr.png")
    cases = {
        "exact": exact,
        "substring": ROOT / "artifacts/agent-experience/reading-fixtures/substring-only.png",
        "pallet": ROOT / "artifacts/native-ocr-stdout-investigation/label with spaces.png",
        "rotated-exif": OUT / "rotated-exif.jpg",
        "mirrored-exif": OUT / "mirrored-exif.jpg",
        "skewed": OUT / "skewed.png",
        "qr": OUT / "qr.png",
    }
    results = []
    for name, source in cases.items():
        start = time.monotonic()
        process = subprocess.run([str(BINARY), "--analyze-image", str(source), "--protocol", "2"],
                                 capture_output=True, text=True, timeout=30, check=True)
        elapsed = time.monotonic() - start
        (OUT / f"{name}.stdout.json").write_text(process.stdout)
        (OUT / f"{name}.stderr.txt").write_text(process.stderr)
        # Both strict generic JSON framing and production Python validation must pass.
        decoded = json.loads(process.stdout)
        reading = NativeVisionReading.model_validate(decoded)
        upright = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
        assert reading.input_size == upright.size
        overlay = upright.copy()
        draw = ImageDraw.Draw(overlay)
        for row in reading.readings:
            if row.polygon:
                points = [(x * overlay.width, y * overlay.height) for x, y in row.polygon]
                draw.line(points + [points[0]], fill="red" if row.kind == "ocr" else "blue", width=3)
        overlay.save(OUT / f"{name}.overlay.png")
        legacy_equal = None
        if name in {"exact", "substring", "pallet"}:
            legacy = subprocess.run([str(BINARY), "--analyze-image", str(source)], capture_output=True,
                                    text=True, timeout=30, check=True)
            legacy_raw = json.loads(legacy.stdout)
            assert set(legacy_raw) == {"texts", "barcodes"}
            old = VisionReading.model_validate(legacy_raw)
            legacy_equal = old.texts == reading.texts and old.barcodes == reading.barcodes
            assert legacy_equal
            (OUT / f"{name}.legacy.json").write_text(legacy.stdout)
        results.append({"case": name, "image": str(source), "image_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "elapsed_s": elapsed, "texts": reading.texts, "barcodes": reading.barcodes,
                        "codepoints": [[f"U+{ord(c):04X}" for c in text] for text in reading.texts],
                        "observation_count": len(reading.readings), "geometry_count": sum(r.box is not None for r in reading.readings),
                        "warnings": reading.warnings, "legacy_projection_equal": legacy_equal,
                        "overlay": str(OUT / f"{name}.overlay.png")})
    rejected = subprocess.run([str(BINARY), "--analyze-image", "unused", "--protocol", "3"],
                              capture_output=True, text=True, timeout=5, check=False)
    assert rejected.returncode == 2 and not rejected.stdout and "Usage" in rejected.stderr
    assert results[-1]["barcodes"] == ["NATIVE-READING-V2-QR"]
    report = {"scope": "Native Apple Vision on generated protocol fixtures; not a task-quality benchmark",
              "binary": str(BINARY.resolve()), "binary_sha256": hashlib.sha256(BINARY.read_bytes()).hexdigest(),
              "schema_version": 2, "request_policy": "apple-vision-en-us-v2", "unsupported_protocol_rejected": True,
              "results": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"cases": len(results), "results": [{"case": r["case"], "texts": r["texts"], "barcodes": r["barcodes"], "geometry_count": r["geometry_count"]} for r in results]}))


if __name__ == "__main__":
    main()
