"""One real existing-adapter call; no labels, evaluation, approval or persistence."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from engine.eval.hashes import file_hash, spec_hash  # noqa: E402
from engine.runtime import run_pipeline  # noqa: E402
from engine.runtime_identity import source_identity  # noqa: E402
from spec.models import PipelineSpec  # noqa: E402


def main() -> None:
    source = Path.home() / "Library/Application Support/VisionApp/datasets/nvidia-smartspaces/Warehouse_026-preview.jpg"
    output = Path(__file__).parent
    pipeline = PipelineSpec.model_validate({
        "name": "Common adapter real person smoke",
        "inputs": {"source": {"type": "image_file", "path": str(source)}},
        "blocks": [
            {"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
            {"id": "roi", "type": "crop", "params": {"box": [.1, 0, .95, 1]}, "in": {"image": "$sample.frame"}},
            {"id": "size", "type": "resize", "params": {"width": 960, "height": 600}, "in": {"image": "$roi.image"}},
            {"id": "detector", "type": "detect_open_vocab",
             "params": {"model": "owlv2-base-patch16", "classes": ["person"], "min_conf": .15},
             "in": {"image": "$size.image"}},
        ],
        "eval": {"metric": "recall", "target": .8},
    })
    before_source = source_identity(ROOT)
    before_image = file_hash(source)
    before_spec = spec_hash(pipeline, output)
    result = run_pipeline(pipeline, output, max_frames=1)
    after_source = source_identity(ROOT)
    after_spec = spec_hash(pipeline, output)
    assert before_source == after_source, "Source changed during the smoke"
    assert before_spec == after_spec, "Model or configuration changed during the smoke"
    assert before_image == file_hash(source), "Input changed during the smoke"
    frame = result.frames[0]
    assert len(frame.inferences) == 1
    evidence = frame.inferences[0]
    assert evidence.block_id == "detector"
    assert evidence.result.input_size == (960, 600)
    assert evidence.result.identity.adapter_id == "owlv2"
    assert evidence.result.identity.model_id == "owlv2-base-patch16"
    assert evidence.result.identity.identity_scope == "local_artifacts_verified"
    assert not evidence.result.identity.unavailable_artifacts
    assert frame.detections, "The chosen smoke image did not yield person hypotheses"
    ox, oy, sx, sy = evidence.input_to_frame
    assert len(frame.detections) == len(evidence.result.detections)
    for observed, mapped in zip(evidence.result.detections, frame.detections, strict=True):
        projected = [ox + observed.box[0] * sx, oy + observed.box[1] * sy,
                     ox + observed.box[2] * sx, oy + observed.box[3] * sy]
        assert all(math.isclose(a, b, abs_tol=1e-10) for a, b in zip(projected, mapped.box, strict=True))
        assert mapped.label == observed.label == "person"
    report = {
        "status": "actual_inference_smoke_not_accuracy_evidence",
        "source_hash_before": before_source, "source_hash_after": after_source,
        "spec_hash_before": before_spec, "spec_hash_after": after_spec,
        "input_sha256": before_image, "input_path": str(source),
        "provenance": {"dataset": "nvidia/PhysicalAI-SmartSpaces", "license": "CC-BY-4.0",
            "attribution": "NVIDIA", "revision": "2cbe9563cbe9f47f846e5c871ee994572bbbc60e",
            "scope": "Previously acquired real Warehouse_026 preview; no new annotation or review"},
        "pipeline": pipeline.model_dump(mode="json", by_alias=True),
        "run": result.model_dump(mode="json"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["One image is a routing/identity/geometry smoke, not accuracy or throughput evidence.",
                        "No project, human review, evaluation score or approval was created.",
                        "Component timing and model-cache state are unmeasured and remain null."],
    }
    report_path = output / "actual-smoke.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    with Image.open(source) as original:
        overlay = original.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    for detection in frame.detections:
        x0, y0, x1, y1 = detection.box
        box = (x0 * overlay.width, y0 * overlay.height, x1 * overlay.width, y1 * overlay.height)
        draw.rectangle(box, outline="lime", width=4)
        draw.text((box[0], max(0, box[1] - 14)), f"person {detection.confidence:.3f} hypothesis", fill="lime")
    overlay.save(output / "actual-smoke-overlay.jpg", quality=92)
    print(json.dumps({"report": str(report_path), "source_hash": before_source,
                      "hypotheses": len(frame.detections), "elapsed_s": result.elapsed_s,
                      "adapter_total_ms": evidence.result.timing.total_ms,
                      "provider": evidence.result.identity.provider}))


if __name__ == "__main__":
    main()
