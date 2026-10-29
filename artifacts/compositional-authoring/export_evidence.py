"""Validate/export captured composition evidence without inference or workspace writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*")) if path.is_file()}


def safe(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = {"api_key", "access_token", "refresh_token", "authorization", "password", "secret"}
        assert not forbidden.intersection(str(key).lower() for key in value), "Credential field in export"
        for child in value.values():
            safe(child)
    elif isinstance(value, list):
        for child in value:
            safe(child)


def write(root: Path, name: str, value: Any) -> str:
    safe(value)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return name


def receipt(path: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(REPO)), "sha256": digest(path)}


def calls(operation: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": call["id"], "kind": call["kind"], "name": call["name"], "status": call["status"],
             "elapsed_s": (call["ended_ns"] - call["started_ns"]) / 1e9 if call["ended_ns"] else None,
             "error": call["error"]} for call in operation["calls"]]


def responses(operation: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"call_id": call["id"], "response": call["result"], "error": call["error"],
             "retry_feedback": [part["content"] for message in call["request"].get("messages", [])
                                for part in message.get("parts", []) if part.get("part_kind") == "retry-prompt"]}
            for call in operation["calls"] if call["kind"] == "llm"]


def export(workspace: Path, output: Path) -> None:
    from run_live import inspect_candidate

    from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
    from agent.replay import replay_operation
    from agent.state_contracts import AgentOperation
    from engine.builds.refinement_edits import apply_edit
    from engine.runtime_identity import source_identity
    from spec.models import PipelineSpec, RunResult
    from spec.platform import BuildPlan
    from spec.refinement import RefinementContext

    workspace, output = workspace.resolve(), output.resolve()
    assert workspace.is_relative_to(REPO / ".visionapp")
    assert output.is_relative_to(Path(__file__).resolve().parent) and not output.exists()
    before = snapshot(workspace)
    initial = read(workspace / "report.json")
    frozen_source = source_identity(REPO)
    assert frozen_source == initial["source_identity"] and initial["passed"]
    output.mkdir(parents=True)
    summary: dict[str, Any] = {"passed": False, "source_identity": frozen_source,
        "scope": "Actual Qwen3-14B Q4_K_M planner and Apple Vision on generated software fixtures. "
                 "Checks composition, execution and a requested follow-up; not an adaptive optimization loop or accuracy acceptance.",
        "planner_alias": initial["planner_model"],
        "planner_identity_scope": "Local server alias; model filename corroborated by server launch configuration, not a weights hash in planner receipts",
        "native_binary_sha256": initial["native_binary_sha256"], "initial_raw_report": receipt(workspace / "report.json"),
        "optional_mixed_detector_case": "not_run", "cases": []}
    for case in initial["cases"]:
        folder = case["case"]
        operation_path = Path(case["raw_operation_paths"][0])
        raw = read(operation_path)
        operation = AgentOperation.model_validate(raw)
        saved = BuildPlan.model_validate(read(Path(case["saved_plan_path"])))
        preview = read(Path(case["preview_path"]))
        result = operation.result
        assert result is not None and operation.decision is not None and operation.decision.schema_version == "0.2"
        checks: dict[str, Any] = {"assertions": []}
        inspect_candidate(checks, folder, result.candidates[0], saved, preview["frames"], None)
        assert all(check["passed"] for check in checks["assertions"])
        replay = replay_operation(operation)
        assert replay.reproduced and replay.dry_run and not replay.effects_executed
        artifacts = {
            "decision": write(output, f"{folder}/decision.json", raw["decision"]),
            "plan": write(output, f"{folder}/plan.json", read(Path(case["saved_plan_path"]))),
            "preview": write(output, f"{folder}/preview.json", preview),
            "replay": write(output, f"{folder}/replay.json", replay.model_dump(mode="json", by_alias=True)),
            "model_responses": write(output, f"{folder}/model-responses.json", responses(raw)),
        }
        summary["cases"].append({"case": folder, "passed": True, "prompt": case["goal"],
            "project_id": case["project_id"], "operation_id": operation.id, "raw_operation": receipt(operation_path),
            "elapsed_s": case["elapsed_s"], "calls": calls(raw), "assertions": checks["assertions"], "artifacts": artifacts})

    original_path = workspace / "refinement-report.json"
    failed = read(original_path)
    safe(failed)
    destination = output / "refinement/harness-failure-original.json"
    destination.parent.mkdir(parents=True)
    shutil.copyfile(original_path, destination)
    assert digest(original_path) == digest(destination)
    assert not failed["passed"]
    assert [name for name, passed in failed["assertions"].items() if not passed] == ["actual_new_pixels_and_false_comparison"]
    status, operation = failed["status"], failed["operation"]
    project_root = workspace / "projects" / failed["project_id"]
    build = read(project_root / "build.json")
    decision = RefinementDecision.model_validate(build["refinement_decisions"][-1])
    context_call = next(call for call in operation["calls"] if call["name"] == "build_refinement_context")
    context = RefinementContext.model_validate(context_call["result"])
    validate_refinement_intent(decision, failed["prompt"], context)
    reconstructed = [candidate.model_copy(deep=True) for candidate in context.candidates]
    for patch in decision.patches:
        indices = range(len(reconstructed)) if patch.target_scope() == "all" else [context.selected_candidate_index]
        for index in indices:
            apply_edit(reconstructed[index], patch, {})
    current = read(project_root / "project.json")
    saved = BuildPlan.model_validate(status["plan"])
    assert reconstructed == saved.candidates == [PipelineSpec.model_validate(value) for value in current["candidates"]]
    preview = RunResult.model_validate(status["preview"])
    frame = preview.frames[0]
    inference = frame.inferences[0]
    comparison = frame.comparisons[0]
    refine_call = next(call for call in operation["calls"] if call["name"] == "build_refine")
    checks = dict(failed["assertions"])
    checks["actual_new_pixels_and_false_comparison"] = (len(preview.frames) == 1
        and inference.result.input_size == (900, 300) and inference.input_to_frame == (.5, 0, .5, 1)
        and [row.text for row in inference.result.readings] == ["WRONG-111"]
        and comparison.expected == "ABC-990" and comparison.mode == "exact" and not comparison.matched)
    checks["captured_tool_preview_equals_saved_preview"] = refine_call["result"]["preview"] == status["preview"]
    checks["reconstructed_patches_equal_saved_and_current_graph"] = True
    checks["captured_batch_equals_model_decision"] = refine_call["request"]["batch"]["patches"] == [patch.model_dump(mode="json") for patch in decision.patches]
    checks["no_review_eval_approval"] = (not any(row["reviewed"] for row in read(project_root / "annotations.json")["annotations"])
        and not current["evaluations"] and current["deployment_id"] is None and current["approval_scope"] is None)
    assert all(checks.values()), checks
    reconstruction = {"reproduced": True, "dry_run": True, "effects_executed": False,
        "scope": "Pure captured refinement patch reconstruction; not replay of the unfinished build/review state machine",
        "candidates": [candidate.model_dump(mode="json", by_alias=True) for candidate in reconstructed]}
    artifacts = {
        "original_harness_failure": "refinement/harness-failure-original.json",
        "decision": write(output, "refinement/decision.json", decision.model_dump(mode="json")),
        "preview": write(output, "refinement/preview.json", status["preview"]),
        "plan": write(output, "refinement/plan.json", status["plan"]),
        "reconstruction": write(output, "refinement/reconstruction.json", reconstruction),
        "model_responses": write(output, "refinement/model-responses.json", responses(operation)),
    }
    summary["refinement"] = {"passed": True, "prompt": failed["prompt"], "elapsed_s": failed["elapsed_s"],
        "status": status["status"], "next_action": status["next_action"], "assertions": checks,
        "calls": calls(operation), "raw_build": receipt(project_root / "build.json"), "original_report": receipt(original_path),
        "harness_correction": {"original_expected_transform": [.5, 0, 1, 1], "correct_expected_transform": [.5, 0, .5, 1],
            "reason": "input_to_frame stores offset_x,offset_y,scale_x,scale_y. Crop box uses x0,y0,x1,y1.",
            "new_model_calls": 0, "new_inference_calls": 0, "original_failure_preserved": True}, "artifacts": artifacts}
    (output / "fixtures").mkdir()
    for path in sorted((workspace / "fixtures").iterdir()):
        shutil.copyfile(path, output / "fixtures" / path.name)
    summary["workspace_unchanged"] = before == snapshot(workspace)
    summary["production_source_unchanged"] = source_identity(REPO) == frozen_source
    assert summary["workspace_unchanged"] and summary["production_source_unchanged"]
    test_log = Path(__file__).resolve().parent / "full-tests-final.log"
    summary["automated_validation"] = {"result": test_log.read_text().strip().splitlines()[-1], "log": receipt(test_log)}
    summary["exported_files_sha256"] = snapshot(output)
    summary["passed"] = True
    write(output, "final-report.json", summary)
    print(json.dumps({"passed": True, "workspace_unchanged": True, "source_identity": frozen_source,
                      "report": str(output / "final-report.json"), "initial_cases": 2, "refinement": "captured success revalidated"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "evidence-final")
    args = parser.parse_args()
    export(args.workspace, args.output)
