"""Run real Apple OCR on frozen public word crops; score only after saving outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from engine.blocks.reading import read_native
from engine.eval.reading import NORMALIZATION, reading_errors


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_native(manifest: Path, binary: Path, output: Path) -> None:
    source = json.loads(manifest.read_text())
    rows = [crop for image in source["images"] for crop in image["selected_crops"]]
    os.environ["VISION_APP_BINARY"] = str(binary.resolve())
    identity = {"binary_sha256": sha(binary), "macos": platform.mac_ver()[0],
                "kernel": platform.release(), "architecture": platform.machine()}
    # Construct inference inputs without transcripts or other ground-truth fields.
    inputs = [{"id": row["id"], "path": row["path"], "sha256": row["sha256"]} for row in rows]
    captured = []
    started = time.perf_counter()
    for item in inputs:
        path = Path(item["path"])
        if sha(path) != item["sha256"]:
            raise ValueError("Frozen crop bytes changed")
        begin = time.perf_counter()
        result = {"id": item["id"], "input_sha256": item["sha256"]}
        try:
            with Image.open(path) as image:
                response = read_native(image.convert("RGB"))
            result.update(response=response.model_dump(mode="json"), error=None)
        except (OSError, ValueError) as error:
            result.update(response=None, error=str(error))
        result["wall_ms"] = (time.perf_counter() - begin) * 1000
        captured.append(result)
        print(item["id"], "failed" if result["error"] else "executed", flush=True)
    if sha(binary) != identity["binary_sha256"]:
        raise ValueError("Native executable changed during inference; results cannot be compared")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schema_version": 1, "model": "apple-vision", "identity": identity,
        "dataset_manifest_sha256": sha(manifest), "network_policy": "Native Apple Vision; no network needed; process sandbox not applied in this run",
        "execution_policy": "One native bridge subprocess per crop; total wall time includes launch, PNG transport and framework work",
        "total_wall_s": time.perf_counter() - started, "results": captured}, indent=2, ensure_ascii=False) + "\n")


def score(manifest: Path, raw: Path, output: Path) -> None:
    source = json.loads(manifest.read_text())
    captured = json.loads(raw.read_text())
    if captured["dataset_manifest_sha256"] != sha(manifest):
        raise ValueError("Inference did not use this frozen manifest")
    rows = [crop for image in source["images"] for crop in image["selected_crops"]]
    results = {row["id"]: row for row in captured["results"]}
    if len(results) != len(captured["results"]) or set(results) != {row["id"] for row in rows}:
        raise ValueError("Missing, duplicate or extra crop results")
    scored = []
    for row in rows:
        result = results[row["id"]]
        if result["input_sha256"] != row["sha256"]:
            raise ValueError("Result input differs from frozen crop")
        response = result.get("response")
        texts = response["texts"] if response is not None else []
        errors = reading_errors([row["expected_text"]], texts)
        scored.append({"id": row["id"], "expected": row["expected_text"], "observed": texts,
                       "error": result["error"], "wall_ms": result["wall_ms"], **asdict(errors)})
    char_edits = sum(row["character_edits"] for row in scored)
    chars = sum(row["expected_characters"] for row in scored)
    word_edits = sum(row["word_edits"] for row in scored)
    words = sum(row["expected_words"] for row in scored)
    timings = sorted(row["wall_ms"] for row in scored)
    summary = {"sample_count": len(scored), "execution_failures": sum(row["error"] is not None for row in scored),
        "exact_count": sum(row["exact_match"] and row["error"] is None for row in scored),
        "character_error_rate": char_edits / chars, "word_error_rate": word_edits / words,
        "median_wall_ms": statistics.median(timings), "p95_wall_ms": timings[max(0, int(len(timings) * .95) - 1)]}
    summary["exact_rate"] = summary["exact_count"] / len(scored)
    output.write_text(json.dumps({"model": captured["model"], "dataset_manifest_sha256": sha(manifest),
        "raw_results_sha256": sha(raw), "normalization": NORMALIZATION, "scope": source["scope"],
        "reviewed": False, "quality_gate_passed": None, "summary": summary, "cases": scored}, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["native", "score"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "native":
        if args.binary is None:
            parser.error("native requires --binary")
        run_native(args.manifest, args.binary, args.output)
    else:
        if args.raw is None:
            parser.error("score requires --raw")
        score(args.manifest, args.raw, args.output)
