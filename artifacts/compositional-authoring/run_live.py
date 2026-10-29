"""Actual local planner/MCP acceptance. Run only after the source tree is frozen.

Generated images are software fixtures, not a recognition-quality benchmark.
No recognition/model response is mocked; no labels are reviewed or evaluated.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
REQUIRED_CASES = ("crop-reading", "parallel-readers")
TEXT = "ABC-990"
QR_VALUE = "VISION-AGENT-PARALLEL-QR"


def write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return str(path.resolve())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_snapshot(root: Path, *, contents: bool) -> dict[str, Any]:
    """Content hashes for replay; metadata only for potentially large model weights."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(root))] = (sha256(path) if contents else
                {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result


def make_fixtures(directory: Path) -> dict[str, Path]:
    import cv2
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    directory.mkdir(parents=True)
    font_path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
    if not font_path.is_file():
        raise FileNotFoundError(f"Fixture font is unavailable: {font_path}")
    crop = Image.new("RGB", (1200, 200), "white")
    draw = ImageDraw.Draw(crop)
    font = ImageFont.truetype(str(font_path), 72)
    draw.text((65, 55), TEXT, fill="black", font=font)
    draw.text((650, 55), "WRONG-111", fill="black", font=font)
    crop_path = directory / "left-half-text.png"
    crop.save(crop_path)
    parallel = Image.new("RGB", (1600, 600), "white")
    ImageDraw.Draw(parallel).text((65, 220), TEXT, fill="black",
                                 font=ImageFont.truetype(str(font_path), 96))
    qr = cv2.QRCodeEncoder_create().encode(QR_VALUE)
    qr_image = ImageOps.expand(Image.fromarray(qr), border=4, fill="white")
    parallel.paste(qr_image.resize((480, 480), Image.Resampling.NEAREST), (1040, 60))
    parallel_path = directory / "printed-text-and-qr.png"
    parallel.save(parallel_path)
    paths = {"crop-reading": crop_path, "parallel-readers": parallel_path}
    write_json(directory / "manifest.json", {
        "provenance": "Original deterministic generated software fixtures; not real-world task validation",
        "generator": str(Path(__file__).resolve()), "font": str(font_path),
        "font_sha256": sha256(font_path), "pillow_version": Image.__version__,
        "opencv_version": cv2.__version__,
        "images": [{"case": case, "path": str(path), "sha256": sha256(path),
                    "printed_text": [TEXT, "WRONG-111"] if case == "crop-reading" else [TEXT],
                    "barcode_payloads": [QR_VALUE] if case == "parallel-readers" else []}
                   for case, path in paths.items()],
        "labels": "Generator expectations remain in this manifest; imported annotations stay unreviewed",
    })
    return paths


def brief_for(case: str, detector: str | None) -> str:
    if case == "crop-reading":
        return ("Build exactly one workflow. Read printed text only in the left half of each image: "
                "crop normalized [0, 0, 0.5, 1], then resize that crop to width 1200 and height 400 "
                "before OCR. Use apple-vision OCR. Compare the recognized text exactly to \"ABC-990\" "
                "and show the comparison result. Do not record events or send alerts. "
                "Use text_accuracy with target 0.9.")
    if case == "parallel-readers":
        return ("Build exactly one workflow that reads both printed text AND barcodes from the whole "
                "image, using apple-vision for both readers. Show both kinds of recognized values "
                "and their regions. Do not crop or resize. Do not record events or send alerts. "
                "Use text_accuracy with target 0.9.")
    return (f"Build exactly one workflow that counts people using {detector} and reads printed text "
            "using apple-vision from the whole image. Detect the person class at confidence 0.25 "
            "and show the total count together with recognized text. Do not crop or resize. "
            "Do not record events or send alerts. Use count_mae with target 1.")


def check(report: dict[str, Any], name: str, passed: bool, detail: Any = None) -> None:
    report["assertions"].append({"name": name, "passed": bool(passed), "detail": detail})


def inspect_candidate(report: dict[str, Any], case: str, candidate: Any,
                      saved: Any, frames: list[Any], detector: str | None) -> None:
    blocks = {block.id: block for block in candidate.blocks}
    kinds = {kind: [block for block in blocks.values() if block.type == kind]
             for kind in ("frame_sample", "crop", "resize", "ocr", "barcode", "match", "detect", "count_per_zone")}
    inference_blocks = [block for block in blocks.values() if block.type in {"ocr", "barcode", "detect", "detect_open_vocab"}]
    bindings = [item for item in saved.model_selections if item.candidate_index == 0]
    check(report, "one_binding_per_inference_node", len(bindings) == len(inference_blocks)
          and {item.block_id for item in bindings} == {block.id for block in inference_blocks})
    check(report, "no_event_sink_or_rule", not any(block.type in {"sink_event", "rule"} for block in blocks.values()))
    check(report, "exactly_one_preview_frame", len(frames) == 1)
    check(report, "no_preview_events", all(not frame["events"] for frame in frames))
    for index, frame in enumerate(frames):
        evidence = {item["block_id"]: item for item in frame["inferences"]}
        check(report, f"frame_{index}_all_inference_nodes_executed", set(evidence) == {b.id for b in inference_blocks})
        check(report, f"frame_{index}_saved_bindings_match_execution", all(
            item.block_id in evidence and evidence[item.block_id]["result"]["identity"]["model_id"] == item.model_id
            and evidence[item.block_id]["result"]["identity"]["capability_id"] == item.capability_id
            for item in bindings))
        for block in inference_blocks:
            actual = evidence.get(block.id)
            if not actual:
                continue
            result = actual["result"]
            if block.type in {"ocr", "barcode"}:
                check(report, f"{block.id}_actual_apple_vision", result["identity"]["model_id"] == "apple-vision"
                      and result["identity"]["identity_scope"] == "system_framework_versioned"
                      and result["identity"]["system_identity"].get("output_protocol") == "2")
                check(report, f"{block.id}_has_region_geometry", any(row.get("box") or row.get("polygon") for row in result["readings"]))
            transform = [0, 0, 0.5, 1] if case == "crop-reading" else [0, 0, 1, 1]
            check(report, f"{block.id}_input_to_frame", actual["input_to_frame"] == transform, actual["input_to_frame"])
            if case == "crop-reading":
                check(report, f"{block.id}_resized_input", result["input_size"] == [1200, 400], result["input_size"])
            elif case == "parallel-readers":
                check(report, f"{block.id}_whole_image_size", result["input_size"] == [1600, 600], result["input_size"])
            if block.type == "ocr" and case != "mixed":
                texts = [row["text"] for row in result["readings"]]
                check(report, f"{block.id}_expected_printed_value", TEXT in texts, texts)
                if case == "crop-reading":
                    check(report, "excluded_right_half_distractor", all("WRONG" not in text for text in texts))
            if block.type == "barcode":
                check(report, "expected_qr_decoded", QR_VALUE in [row["text"] for row in result["readings"]])
        if case == "crop-reading":
            matches = frame.get("comparisons", [])
            check(report, "comparison_observation_without_events", len(matches) == 1 and matches[0]["expected"] == TEXT
                  and matches[0]["mode"] == "exact" and matches[0]["matched"] is True and TEXT in matches[0]["observed"], matches)
        else:
            check(report, "no_unrequested_comparison", not frame.get("comparisons"))
        if case == "mixed":
            check(report, "actual_person_detection", any(row["label"] == "person" for row in frame["detections"]))
            check(report, "actual_positive_count", sum(frame["counts"].values()) > 0, frame["counts"])
            check(report, "actual_ocr_text", any(item["result"]["task"] == "ocr" and item["result"]["readings"] for item in evidence.values()))
    if case == "crop-reading":
        shape = all(len(kinds[kind]) == 1 for kind in ("crop", "resize", "ocr", "match"))
        check(report, "crop_resize_ocr_comparison_nodes", shape)
        if shape:
            crop, resize, reader, match = (kinds[kind][0] for kind in ("crop", "resize", "ocr", "match"))
            check(report, "literal_crop_resize_parameters", crop.params["box"] == [0, 0, 0.5, 1]
                  and resize.params == {"width": 1200, "height": 400})
            check(report, "crop_then_resize_then_ocr_then_match", resize.inputs["image"] == f"${crop.id}.image"
                  and reader.inputs["image"] == f"${resize.id}.image" and match.inputs["text"] == f"${reader.id}.text")
    else:
        second = "barcode" if case == "parallel-readers" else "detect"
        shape = len(kinds["ocr"]) == len(kinds[second]) == 1
        check(report, "two_parallel_reader_or_detector_branches", shape)
        check(report, "whole_frame_no_transforms", not kinds["crop"] and not kinds["resize"])
        if shape:
            check(report, "branches_share_input", kinds["ocr"][0].inputs["image"] == kinds[second][0].inputs["image"])
        if case == "mixed":
            check(report, "requested_real_detector", any(item.model_id == detector for item in bindings))
            check(report, "count_node_exists", len(kinds["count_per_zone"]) == 1)


async def run_case(case: str, image: Path, args: argparse.Namespace,
                   service: Any, evidence_dir: Path) -> dict[str, Any]:
    from agent.planner import plan
    from agent.replay import replay_operation
    from engine.agent_state import AgentStateStore

    project = service.create_project(f"Composition acceptance: {case}", "custom")
    service.import_media(project.id, [str(image)])
    goal = brief_for(case, args.detector_model)
    report: dict[str, Any] = {"case": case, "passed": False, "project_id": project.id,
        "goal": goal, "input": {"path": str(image), "sha256": sha256(image)}, "assertions": [],
        "scope": "Actual models on a supplied image; software integration only" if case == "mixed" else
                 "Actual Apple Vision on deterministic generated software fixtures"}
    root = service.root(project.id)
    store = AgentStateStore(service)
    started = time.monotonic()
    try:
        print(json.dumps({"case": case, "status": "planning", "project_id": project.id}), flush=True)
        result = await plan(goal, "media", {"project_id": project.id, "mcp_data_dir": str(service.repository.root),
            "use_case": "custom", "model_url": "http://127.0.0.1:1234/v1", "planner_model": "visionapp-planner",
            **({"detector_model": args.detector_model} if case == "mixed" else {})})
        report["result_path"] = write_json(evidence_dir / case / "result.json", result.model_dump(mode="json", by_alias=True))
        check(report, "one_executable_candidate_without_clarification", len(result.candidates) == 1 and not result.questions)
        if len(result.candidates) == 1:
            store.commit_plan(project.id, result.operation_id, result, goal)
        operation = store.operation(project.id, result.operation_id)
        check(report, "typed_graph_decision_0_2", operation.decision is not None
              and operation.decision.schema_version == "0.2" and len(operation.decision.graphs) == 1)
        if operation.decision:
            report["decision_path"] = write_json(evidence_dir / case / "decision.json", operation.decision.model_dump(mode="json"))
        plans = [saved for saved in store.platform.plans(project.id) if saved.operation_id == operation.id]
        check(report, "immutable_saved_plan", len(plans) == 1)
        previews = [call for call in operation.calls if call.name == "pipeline_run" and call.status == "completed"]
        check(report, "actual_mcp_preview", len(previews) == 1)
        check(report, "actual_local_model_call", any(call.kind == "llm" and call.status == "completed" for call in operation.calls))
        if len(plans) == len(previews) == len(result.candidates) == 1:
            saved, preview = plans[0], previews[0].result or {}
            report["saved_plan_path"] = str(store.platform.path(project.id, "plans", saved.id))
            report["model_bindings"] = [item.model_dump(mode="json") for item in saved.model_selections]
            report["preview_path"] = write_json(evidence_dir / case / "preview.json", preview)
            check(report, "saved_candidates_equal_returned_candidates", saved.candidates == result.candidates)
            check(report, "captured_options_binding", bool(saved.planning_options_artifact_id))
            inspect_candidate(report, case, result.candidates[0], saved, preview.get("frames", []), args.detector_model)
        before = file_snapshot(service.repository.root, contents=True)
        replay_started = time.monotonic()
        replay = replay_operation(operation)
        replay_elapsed = time.monotonic() - replay_started
        after = file_snapshot(service.repository.root, contents=True)
        check(report, "replay_reproduced_without_effects", replay.reproduced and replay.dry_run and not replay.effects_executed
              and before == after, {"reproduced": replay.reproduced, "errors": replay.errors, "workspace_unchanged": before == after})
        report["replay_path"] = write_json(evidence_dir / case / "replay.json", replay.model_dump(mode="json", by_alias=True))
        report["replay_elapsed_s"] = replay_elapsed
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        # Direct file reads retain the original failure before reconciliation can change its status.
        operations = sorted((root / "agent-runs").glob("*.json"), key=lambda path: path.stat().st_mtime_ns)
        report["raw_operation_paths"] = [str(path) for path in operations]
        if operations:
            raw = json.loads(operations[-1].read_text())
            report["operation_id"], report["operation_status"] = raw["id"], raw["status"]
            report["operation_timing"] = [{"id": call["id"], "kind": call["kind"], "name": call["name"],
                "status": call["status"], "elapsed_s": (call["ended_ns"] - call["started_ns"]) / 1e9 if call["ended_ns"] else None,
                "error": call["error"]} for call in raw["calls"]]
        current = service.get_project(project.id)
        check(report, "no_stored_events", not service.events(project.id))
        check(report, "annotations_remain_unreviewed", not any(row.reviewed for row in service.annotations(project.id).annotations))
        check(report, "no_evaluation_or_approval", not current.evaluations and current.deployment_id is None and current.approval_scope is None)
        report["elapsed_s"] = time.monotonic() - started
        report["passed"] = not report.get("error") and all(row["passed"] for row in report["assertions"])
        write_json(evidence_dir / case / "report.json", report)
        print(json.dumps({"case": case, "passed": report["passed"], "elapsed_s": report["elapsed_s"],
                          "failures": [row["name"] for row in report["assertions"] if not row["passed"]],
                          "error": report.get("error", {}).get("message")}), flush=True)
    return report


async def run(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)  # MCP's python -m must resolve this checkout, not an installed wheel.
    os.environ.update(VISION_APP_BINARY=str(REPO / "app/.build/debug/VisionApp"),
                      VISION_MODELS_DIR=str(args.models_dir.resolve()), HF_HUB_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    from engine.models.manager import list_models
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService

    workspace = args.workspace.resolve()
    if not workspace.is_relative_to(REPO / ".visionapp") or workspace.exists():
        raise ValueError("Use a NEW isolated --workspace below this checkout's .visionapp directory")
    binary = Path(os.environ["VISION_APP_BINARY"])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"Build the current native binary before running: {binary}")
    cases = list(REQUIRED_CASES) if args.case == "required" else [args.case]
    if "mixed" in cases:
        if not args.mixed_image or not args.mixed_image.is_file() or not args.detector_model:
            raise ValueError("mixed requires --mixed-image and --detector-model; it is never silently skipped")
        model = next((item for item in list_models() if item["id"] == args.detector_model), None)
        if not model or not model["available"] or model["synthetic"] or args.detector_model == "apple-vision":
            raise ValueError("mixed requires an already installed real detector; no automatic provisioning")
    source_before = source_identity(REPO)
    if args.source_identity and args.source_identity != source_before:
        raise ValueError("Current source identity differs from --source-identity")
    cache_before = file_snapshot(args.models_dir, contents=False)
    workspace.mkdir(parents=True)
    evidence_dir = workspace / "acceptance-evidence"
    report: dict[str, Any] = {"passed": False, "required_acceptance_complete": False,
        "selected_cases": cases, "not_run": [case for case in (*REQUIRED_CASES, "mixed") if case not in cases],
        "workspace": str(workspace), "source_identity": source_before, "python": sys.executable,
        "native_binary": str(binary), "native_binary_sha256": sha256(binary),
        "model_cache": str(args.models_dir.resolve()), "planner_url": "http://127.0.0.1:1234/v1",
        "planner_model": "visionapp-planner", "cases": []}
    started = time.monotonic()
    try:
        fixtures = make_fixtures(workspace / "fixtures")
        if args.mixed_image:
            fixtures["mixed"] = args.mixed_image.resolve()
        service = WorkspaceService(workspace)
        for case in cases:
            report["cases"].append(await run_case(case, fixtures[case], args, service, evidence_dir))
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        report["source_unchanged"] = source_identity(REPO) == source_before
        report["native_binary_unchanged"] = sha256(binary) == report["native_binary_sha256"]
        report["model_cache_metadata_unchanged"] = file_snapshot(args.models_dir, contents=False) == cache_before
        report["elapsed_s"] = time.monotonic() - started
        report["passed"] = (not report.get("error") and len(report["cases"]) == len(cases)
            and all(row["passed"] for row in report["cases"]) and report["source_unchanged"]
            and report["native_binary_unchanged"] and report["model_cache_metadata_unchanged"])
        report["required_acceptance_complete"] = report["passed"] and set(REQUIRED_CASES).issubset(cases)
        report_path = write_json(workspace / "report.json", report)
        print(json.dumps({"passed": report["passed"], "required_acceptance_complete": report["required_acceptance_complete"],
                          "report": report_path, "elapsed_s": report["elapsed_s"]}), flush=True)
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("required", *REQUIRED_CASES, "mixed"), default="required")
    parser.add_argument("--workspace", type=Path, default=REPO / ".visionapp/compositional-authoring" /
                        datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ"))
    parser.add_argument("--models-dir", type=Path, default=Path.home() / "Library/Application Support/VisionApp/models")
    parser.add_argument("--source-identity", help="Optional exact engine source identity to pin a frozen checkout")
    parser.add_argument("--mixed-image", type=Path, help="Existing image with real people and legible printed text")
    parser.add_argument("--detector-model", help="Installed real detector ID; required for optional mixed case")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
