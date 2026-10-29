"""Actual local-model follow-up on a successful isolated graph acceptance project."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


async def run(report_path: Path) -> int:
    from engine.builds.manager import BuildManager
    from engine.platform.store import PlatformStore
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService

    initial = json.loads(report_path.read_text())
    workspace = Path(initial["workspace"])
    if not workspace.resolve().is_relative_to(REPO / ".visionapp") or not initial["passed"]:
        raise ValueError("Use a passing acceptance report from an isolated checkout workspace")
    os.chdir(REPO)
    os.environ.update(VISION_APP_BINARY=initial["native_binary"], VISION_MODELS_DIR=initial["model_cache"],
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    case = next(row for row in initial["cases"] if row["case"] == "crop-reading")
    project_id = case["project_id"]
    service = WorkspaceService(workspace)
    settings = service.repository.settings()
    settings.model_url, settings.planner_model = initial["planner_url"], initial["planner_model"]
    service.repository.save_settings(settings)
    platform = PlatformStore(service)
    original = service.get_project(project_id).candidates[0].model_copy(deep=True)
    original_bindings = platform.plans(project_id)[-1].model_selections
    manager = BuildManager(service)
    prompt = ("Change the OCR crop to the right half [0.5, 0, 1, 1] and resize it to 900 by 300 pixels. "
              "Keep the existing comparison and event behavior unchanged.")
    source = source_identity(REPO)
    started = time.monotonic()
    await manager.start(project_id, prompt)
    await manager.tasks[project_id]
    status = manager.status(project_id)
    record = manager.store.get(project_id)
    current = service.get_project(project_id)
    spec = current.candidates[0]
    frames = status.preview.frames if status.preview else []
    revised = next((plan for plan in reversed(platform.plans(project_id)) if plan.candidates == current.candidates), None)
    before_nodes = {block.id: block for block in original.blocks}
    unchanged = all(block == before_nodes[block.id] for block in spec.blocks if block.type not in {"crop", "resize"})
    assertions = {
        "actual_local_model_call": any(call.kind == "llm" and call.status == "completed" for call in record.operation.calls),
        "actual_refinement_tool": any(call.name == "build_refine" and call.status == "completed" for call in record.operation.calls),
        "paused_for_evidence_without_approval": status.status == "awaiting_review" and status.next_action in {"review_labels", "configure_evaluation"},
        "same_inference_comparison_event_nodes": unchanged,
        "same_saved_node_bindings": revised is not None and revised.model_selections == original_bindings,
        "exact_crop": any(block.type == "crop" and block.params["box"] == [.5, 0, 1, 1] for block in spec.blocks),
        "exact_resize": any(block.type == "resize" and block.params == {"width": 900, "height": 300} for block in spec.blocks),
        "actual_new_pixels_and_false_comparison": len(frames) == 1 and any(
            # input_to_frame is offset_x, offset_y, scale_x, scale_y, not crop xyxy.
            item.result.input_size == (900, 300) and item.input_to_frame == (.5, 0, .5, 1)
            and any(row.text == "WRONG-111" for row in item.result.readings) for item in frames[0].inferences)
            and len(frames[0].comparisons) == 1 and not frames[0].comparisons[0].matched
            and frames[0].comparisons[0].expected == "ABC-990",
        "no_events": not service.events(project_id) and all(not frame.events for frame in frames),
        "no_review_eval_approval": not any(row.reviewed for row in service.annotations(project_id).annotations)
            and not current.evaluations and current.deployment_id is None and current.approval_scope is None,
        "source_unchanged": source_identity(REPO) == source,
    }
    output = workspace / "refinement-report.json"
    result = {"passed": all(assertions.values()), "source_identity": source, "workspace": str(workspace),
              "project_id": project_id, "prompt": prompt, "assertions": assertions,
              "elapsed_s": time.monotonic() - started, "initial_report": str(report_path.resolve()),
              "status": status.model_dump(mode="json", by_alias=True),
              "operation": record.operation.model_dump(mode="json", by_alias=True),
              "scope": "Actual local planner and Apple Vision on a generated software fixture; no quality or approval claim"}
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": result["passed"], "failed": [key for key, value in assertions.items() if not value],
                      "report": str(output), "status": status.status, "message": status.message,
                      "elapsed_s": result["elapsed_s"]}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    raise SystemExit(asyncio.run(run(parser.parse_args().report)))
