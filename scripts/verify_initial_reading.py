"""Actual native OCR plus conditional match execution on two generated text fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import plan_from_context
from agent.task_validation import validate_custom_inputs
from engine.runtime import run_pipeline


def verify(root: Path, binary: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    media = root / "media"
    media.mkdir(exist_ok=True)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 80)
    for name, text in (("01-match.png", "ABC-990"), ("02-mismatch.png", "WRONG-111")):
        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).text((50, 65), text, fill="black", font=font)
        image.save(media / name)
    os.environ["VISION_APP_BINARY"] = str(binary.resolve())
    rows: list[dict[str, object]] = []
    policies: tuple[Literal["all", "matched", "mismatched"], ...] = ("all", "matched", "mismatched")
    for emit in policies:
        brief = ("Read printed labels and check whether the text exactly equals ABC-990." if emit == "all"
                 else "Read printed labels and create a local event when the text "
                 + ("exactly equals ABC-990." if emit == "matched" else "does not exactly match ABC-990."))
        decision = PlanDecision(message="Actual OCR fixture check", choices=[PatternChoice(
            use_case="custom", pipeline_type="ocr", expected_text="ABC-990", match_mode="exact",
            match_emit=emit, metric="text_accuracy", target=.95)])
        validate_custom_inputs(decision, brief, [])
        plan = plan_from_context(decision, brief, "media", "fixture-color-v1")
        run = run_pipeline(plan.candidates[0], root, max_frames=2)
        assert len(run.frames) == 2
        expected_texts = ["ABC-990", "WRONG-111"]
        for frame, text in zip(run.frames, expected_texts, strict=True):
            assert frame.texts == [text], (frame.texts, text)
            matched = text == "ABC-990"
            should_emit = emit == "all" or (matched if emit == "matched" else not matched)
            assert len(frame.events) == int(should_emit), (emit, frame.events)
            if should_emit:
                assert frame.events[0]["matched"] is matched
        rows.append({"emit": emit, "brief": brief, "summary": plan.message,
                     "run": run.model_dump(mode="json"), "passed": True})
    return {"provenance": "Original generated text images; actual Apple Vision OCR and typed runtime. No LLM, detector quality claim, evaluation or deployment approval.",
            "binary": str(binary.resolve()), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "policies": rows, "passed": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.workdir.resolve(), args.binary.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "policies": ["all", "matched", "mismatched"]}))
