"""Isolated real-scene investigation; evaluator references never enter the planner."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import struct
import sys
import traceback
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "artifacts/a0-investigation/cases/bus-destination-v1"
sys.path.insert(0, str(ROOT))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_identity(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        pixels = b"RGB\0" + struct.pack(">II", *image.size) + image.tobytes()
        return {"file_sha256": sha256(path.read_bytes()), "size": list(image.size),
                "decoded_rgb_sha256": sha256(pixels)}


def load_case(variant: str, media: Path | None = None) -> tuple[dict[str, Any], Path, str]:
    manifest = json.loads((CASE / "manifest.json").read_text())
    selected = next(row for row in manifest["inputs"] if row["variant"] == variant)
    path = (media or ROOT / selected["path"]).resolve(strict=True)
    identity = image_identity(path)
    if any(identity[key] != selected[key] for key in identity):
        raise ValueError("Input differs from the predeclared variant's bytes, size or decoded pixels")
    prompt = (CASE / "planner-prompt.txt").read_text().strip()
    if prompt != manifest["planner_input"]["prompt"]:
        raise ValueError("Planner prompt differs from the frozen case manifest")
    return manifest, path, prompt


def score_preview(preview: dict[str, Any] | None, reference: dict[str, Any]) -> dict[str, Any]:
    """Exact whitespace tokens plus normalized full-frame reading geometry only."""
    expected = reference["expected_case_sensitive_tokens"]
    if preview is None:
        return {"status": "no_selected_preview", "exact_tokens": None, "geometry_inside_display": None,
                "predeclared_preview_check_passed": False, "expected_tokens": expected}
    frames = preview.get("frames", [])
    texts = [text for frame in frames for text in frame.get("texts", [])]
    tokens = [token for text in texts for token in text.split()]
    rows = []
    x0, y0, x1, y1 = reference["display_envelope_xyxy_normalized"]
    for index, frame in enumerate(frames):
        for inference in frame.get("inferences", []):
            ox, oy, sx, sy = inference.get("input_to_frame", [0, 0, 1, 1])
            for reading in inference["result"].get("readings", []):
                box = reading.get("box")
                polygon = reading.get("polygon")
                if box is None and polygon:
                    box = [min(p[0] for p in polygon), min(p[1] for p in polygon),
                           max(p[0] for p in polygon), max(p[1] for p in polygon)]
                mapped = [ox + sx * box[0], oy + sy * box[1], ox + sx * box[2], oy + sy * box[3]] if box else None
                centre = [(mapped[0] + mapped[2]) / 2, (mapped[1] + mapped[3]) / 2] if mapped else None
                rows.append({"frame_index": index, "block_id": inference["block_id"], "text": reading["text"],
                             "source_box": mapped, "source_centre": centre,
                             "inside_display": bool(centre and x0 <= centre[0] <= x1 and y0 <= centre[1] <= y1)})
    exact = Counter(tokens) == Counter(expected)
    geometry = bool(rows) and all(row["inside_display"] for row in rows)
    geometry_covers_text = Counter(token for row in rows for token in row["text"].split()) == Counter(tokens)
    return {"status": "selected_preview_scored", "expected_tokens": expected, "actual_texts": texts,
            "actual_tokens": tokens, "exact_tokens": exact, "geometry_inside_display": geometry,
            "geometry_accounts_for_all_returned_tokens_once": geometry_covers_text, "readings": rows,
            "single_selected_frame": len(frames) == 1,
            "predeclared_preview_check_passed": len(frames) == 1 and exact and geometry and geometry_covers_text,
            "normalization": "Whitespace splitting only; no case, punctuation, spelling or dictionary correction."}


def changed_vision_edges(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Identify inspectable provenance links, without claiming their rationale is sound."""
    actions = snapshot["actions"]
    by_id = {row["id"]: (index, row) for index, row in enumerate(actions)}
    edges = []
    for observation in snapshot["observations"]:
        if observation["result_type"] not in {"run_probe", "construct_workflow"} or not observation["payload"].get("executed"):
            continue
        source_index, source = by_id[observation["action_id"]]
        for later in actions[source_index + 1:]:
            decision = later["decision"]
            action = decision["action"]
            if (action["type"] in {"run_probe", "construct_workflow"}
                    and observation["id"] in decision["based_on_observation_ids"]
                    and action != source["decision"]["action"]):
                edges.append({"observation_id": observation["id"], "from_action_id": source["id"],
                              "to_action_id": later["id"], "to_status": later["status"],
                              "from_action": source["decision"]["action"], "to_action": action,
                              "decision_summary": decision["decision_summary"],
                              "interpretation": "Explicit evidence link and changed vision-action payload; material usefulness and causality require trace review."})
    return edges


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


async def run(args: argparse.Namespace) -> int:
    # These imports and all service operations occur only after CLI parsing.
    from agent.investigation import transport_system
    from engine.investigations.manager import InvestigationManager
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService
    from spec.investigation import InvestigationBudget

    manifest, media, prompt = load_case(args.variant, args.media)
    system = transport_system(args.transport)
    native = args.native_binary.resolve(strict=True)
    folder = args.output_dir or ROOT / ".visionapp/a0-investigation" / datetime.now(UTC).strftime(
        f"case-{manifest['case_id']}-{args.variant}-%Y%m%dT%H%M%S%fZ")
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    source_before = source_identity(ROOT)
    started = monotonic()
    os.environ.update(VISION_APP_BINARY=str(native), VISION_MODELS_DIR=str(args.models_dir.resolve()),
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # The evaluator copy is a sibling of workspace; only scene pixels + prompt
    # are imported. Neither reference geometry nor the alternate variant is bound.
    evaluator = folder / "evaluator-only"
    evaluator.mkdir()
    shutil.copy2(CASE / "manifest.json", evaluator / "manifest.json")
    (folder / "planner-prompt.txt").write_text(prompt + "\n")
    (folder / "system-prompt.txt").write_text(system)
    input_dir = folder / "input"
    input_dir.mkdir()
    frozen_media = input_dir / "scene.jpg"
    shutil.copyfile(media, frozen_media)
    service = WorkspaceService(folder / "workspace")
    settings = service.repository.settings()
    settings.model_url, settings.planner_model = args.model_url, args.model
    settings.investigation_transport = args.transport
    service.repository.save_settings(settings)
    project = service.create_project("Public scene investigation", "custom")
    service.import_media(project.id, [str(frozen_media)])
    imported = service.get_project(project.id)
    assert len(imported.media) == 1 and not imported.fixture
    imported_identity = image_identity(Path(imported.media[0]))
    if imported_identity["decoded_rgb_sha256"] != image_identity(frozen_media)["decoded_rgb_sha256"]:
        raise ValueError("Normal import changed the case pixels")
    budget = InvestigationBudget(max_model_calls=args.max_model_calls, max_actions=args.max_actions,
                                 max_probes=args.max_probes, max_elapsed_s=args.max_elapsed_s)
    setup = {"case_id": manifest["case_id"], "variant": args.variant, "input": image_identity(frozen_media),
             "imported_input": imported_identity, "project_id": project.id, "source_before": source_before,
             "manifest_sha256": sha256((CASE / "manifest.json").read_bytes()),
             "planner_prompt_sha256": sha256(prompt.encode()), "system_prompt_sha256": sha256(system.encode()),
             "harness_sha256": sha256(Path(__file__).read_bytes()), "native_binary": str(native),
             "native_binary_sha256": sha256(native.read_bytes()), "model_url": args.model_url,
             "model": args.model, "label": args.label, "transport": args.transport, "model_identity_scope": "Configured alias; model weights are not independently verified by this harness.",
             "budget": budget.model_dump(mode="json"), "workspace": str(folder / "workspace"),
             "reference_boundary": "Only the objective and one imported image enter the project. Evaluator reference stays outside workspace and is scored after the runner stops."}
    write_json(folder / "setup.json", setup)
    manager = InvestigationManager(service)
    task_id = None
    failure = None
    print(json.dumps({"folder": str(folder), "project_id": project.id, "source_identity": source_before}), flush=True)
    try:
        task = await manager.start(project.id, prompt, "predeclared-public-scene", budget)
        task_id = task.id
        runner = manager.tasks.get((project.id, task.id))
        seen: set[str] = set()
        while runner is not None and not runner.done():
            for action in manager.store.actions(project.id, task.id):
                if action.id not in seen and action.status != "reserved":
                    seen.add(action.id)
                    print(json.dumps({"action": action.action.type, "status": action.status,
                                      "based_on": action.decision.based_on_observation_ids,
                                      "purpose": action.decision.decision_summary}), flush=True)
            await asyncio.sleep(2)
        if runner is not None:
            await runner
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        await manager.close()
    if task_id is None:
        tasks = manager.store.service.root(project.id) / "investigations"
        saved = list(tasks.glob("*/task.json"))
        if len(saved) == 1:
            task_id = saved[0].parent.name
    snapshot = manager.snapshot(project.id, task_id).model_dump(mode="json") if task_id else None
    write_json(folder / "execution.json", snapshot)
    calls = manager.store.model_calls(project.id, task_id) if task_id else []
    write_json(folder / "model-calls.json", [call.model_dump(mode="json") for call in calls])
    preview = None
    selected = None
    if snapshot:
        selected = next((row for row in snapshot["observations"] if row["id"] == snapshot["state"]["preview_observation_id"]), None)
        if (selected and selected["status"] == "completed" and selected["payload"].get("preview_success")
                and selected["payload"].get("workflow_revision_id") == snapshot["state"]["selected_workflow_revision"]):
            preview = selected["payload"].get("preview")
    write_json(folder / "selected-preview.json", preview)
    reference = manifest["reference_evaluator_only"]
    score = score_preview(preview, reference)
    final_project = service.get_project(project.id)
    side_effects = {"persisted_events": len(service.events(project.id)), "project_candidates": len(final_project.candidates),
                    "evaluations": len(final_project.evaluations), "deployment_id": final_project.deployment_id,
                    "review_records": len(service.review(project.id)),
                    "reviewed_annotations": sum(row.reviewed for row in service.annotations(project.id).annotations),
                    "fixture": final_project.fixture}
    source_after = source_identity(ROOT)
    state = snapshot["state"] if snapshot else None
    report = {**setup, "source_after": source_after, "source_unchanged": source_before == source_after,
              "elapsed_s": monotonic() - started, "failure": failure, "task_id": task_id, "state": state,
              "raw_evidence": {"execution": "execution.json", "model_calls": "model-calls.json",
                               "selected_preview": "selected-preview.json",
                               "sha256": {name: sha256((folder / name).read_bytes()) for name in
                                          ["execution.json", "model-calls.json", "selected-preview.json"]},
                               "immutable_artifacts": "workspace/projects/" + project.id + "/investigations/" + (task_id or "")},
              "selected_preview_observation": selected["id"] if selected else None,
              "selected_workflow_revision_id": selected["payload"].get("workflow_revision_id") if selected else None,
              "selected_spec_hash": selected["payload"].get("spec_hash") if selected else None,
              "reference_evaluator_only": reference, "reference_check": score, "side_effects": side_effects,
              "adaptive_trace_candidate_edges": changed_vision_edges(snapshot) if snapshot else [],
              "adaptive_trace_review_required": True,
              "degraded_uncertainty_review": {"required": args.variant == "degraded",
                  "status": "not_automatically_scored", "criterion": manifest["predeclared_checks"]["negative_output"]},
              "unsupported_draft_ready": bool(state and state["status"] == "draft_ready" and not score["predeclared_preview_check_passed"]),
              "provenance": manifest["source"], "limitations": manifest["prior_exposure_and_limitations"],
              "scope": "One real public scene and a predeclared degraded derivative. Exact preview scoring is diagnostic, not A0 acceptance, warehouse/production accuracy, generalization or approval. No action sequence is forced; awaiting input is recorded without an automatic answer."}
    write_json(folder / "report.json", report)
    print(json.dumps({"status": state["status"] if state else "harness_failed", "report": str(folder / "report.json"),
                      "preview_check": score["predeclared_preview_check_passed"], "source_unchanged": source_before == source_after}), flush=True)
    return 1 if failure or source_before != source_after else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--variant", choices=["original", "degraded"], required=True)
    result.add_argument("--media", type=Path, help="Optional copy of the chosen frozen variant; exact bytes and pixels must match")
    result.add_argument("--model-url", default="http://127.0.0.1:1234/v1")
    result.add_argument("--model", default="visionapp-planner")
    result.add_argument("--transport", choices=["structured_json", "decision_function"], default="structured_json")
    result.add_argument("--label", default="Real-scene qualification")
    result.add_argument("--output-dir", type=Path, help="Fresh output directory; default is ignored .visionapp/a0-investigation")
    result.add_argument("--native-binary", type=Path, default=ROOT / "dist/VisionApp.app/Contents/MacOS/VisionApp")
    result.add_argument("--models-dir", type=Path, default=Path.home() / "Library/Application Support/VisionApp/models")
    result.add_argument("--max-model-calls", type=int, default=20)
    result.add_argument("--max-actions", type=int, default=16)
    result.add_argument("--max-probes", type=int, default=6)
    result.add_argument("--max-elapsed-s", type=float, default=900)
    result.add_argument("--validate-input", action="store_true", help="Verify frozen input and prompt only; no service or inference calls")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.validate_input:
        manifest, path, prompt = load_case(args.variant, args.media)
        print(json.dumps({"case_id": manifest["case_id"], "variant": args.variant, "input": image_identity(path),
                          "prompt_sha256": sha256(prompt.encode()), "inference_executed": False}, indent=2))
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
