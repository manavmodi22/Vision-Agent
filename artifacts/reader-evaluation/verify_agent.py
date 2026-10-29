"""Actual local planner/MCP construction with explicit Apple OCR and rich regions.

Uses two unreviewed public scene-text images in an isolated workspace; no labels
are approved, no quality evaluation is created, and no events are recorded.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

import agent
import engine
import mcp_server
import spec
from agent.planner import plan
from engine.agent_state import AgentStateStore
from engine.platform.planning_options import planning_options
from engine.runtime_identity import source_identity
from engine.service import WorkspaceService


async def verify(workspace: Path, output: Path) -> None:
    if workspace.exists() or output.exists():
        raise ValueError("Use new paths; retain prior work and evidence")
    repo = Path(__file__).resolve().parents[2]
    imported_roots = {package.__name__: str(Path(package.__file__).resolve().parent.parent)
                      for package in (agent, engine, mcp_server, spec)}
    assert all(Path(root) == repo for root in imported_roots.values()), imported_roots
    expected_hash = source_identity(repo)
    manifest = json.loads((repo / "artifacts/reader-evaluation/textocr-manifest.json").read_text())
    paths = [repo / ".visionapp/datasets/textocr-v0.1/images" / (row["id"] + ".jpg") for row in manifest["images"][:2]]
    assert len(paths) == 2 and all(path.is_file() for path in paths)
    service = WorkspaceService(workspace.resolve())
    project = service.create_project("OCR agent integration on public scene text", "custom")
    service.import_media(project.id, [str(path) for path in paths])
    goal = ("Read all printed text in these images and show the recognized regions and values. "
            "Build exactly one OCR workflow with apple-vision, using English (en-US) and a text_accuracy target of 0.9. "
            "Do not create events or send alerts.")
    options = planning_options(service, project.id, request=goal)
    assert any(item.model_id == "apple-vision" for item in options.eligible_models)
    report: dict[str, object] = {"passed": False, "source_identity": expected_hash,
        "imported_package_roots": imported_roots,
        "goal": goal, "project_id": project.id, "workspace": str(workspace.resolve()),
        "source_scope": "Two public TextOCR/Open Images scene-text images, unreviewed. This tests prompt-to-executed-OCR, not recognition accuracy.",
        "inputs": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
        "planning_options": options.model_dump(mode="json")}
    started = time.monotonic()
    try:
        result = await plan(goal, "media", {"project_id": project.id,
            "mcp_data_dir": str(workspace.resolve()), "use_case": "custom",
            "model_url": "http://127.0.0.1:1234/v1", "planner_model": "visionapp-planner"})
        store = AgentStateStore(service)
        operation = store.operation(project.id, result.operation_id)
        report.update(result=result.model_dump(mode="json", by_alias=True),
                      operation=operation.model_dump(mode="json", by_alias=True))
        assert len(result.candidates) == 1, "Expected one executable candidate; see retained planner result and operation"
        saved_plans = store.platform.plans(project.id)
        assert saved_plans, "Agent returned a candidate without an immutable saved plan"
        saved = saved_plans[-1]
        assert len(saved.model_selections) == 1 and saved.model_selections[0].model_id == "apple-vision"
        candidate = result.candidates[0]
        reader = next(block for block in candidate.blocks if block.type == "ocr")
        assert reader.params["model"] == "apple-vision"
        assert candidate.eval.metric == "text_accuracy" and candidate.eval.target == .9
        assert not any(block.type in {"rule", "sink_event"} for block in candidate.blocks)
        calls = sum(call.kind == "llm" and call.status == "completed" for call in operation.calls)
        assert calls > 0 and saved.planning_options_artifact_id
        previews = [call.result for call in operation.calls
                    if call.name == "pipeline_run" and call.status == "completed"]
        assert len(previews) == 1 and previews[0] and previews[0].get("frames"), "Expected actual completed sample inference"
        frames = previews[0]["frames"]
        assert len(frames) == 2
        for frame in frames:
            evidence = [item for item in frame["inferences"] if item["result"]["task"] == "ocr"]
            assert evidence and evidence[0]["result"]["identity"]["model_id"] == "apple-vision"
            assert evidence[0]["result"]["identity"]["system_identity"]["output_protocol"] == "2"
        assert any(item["polygon"] for frame in frames for block in frame["inferences"] for item in block["result"]["readings"])
        store.commit_plan(project.id, result.operation_id, result, goal)
        assert not service.events(project.id) and not service.get_project(project.id).evaluations
        assert not any(row.reviewed for row in service.annotations(project.id).annotations)
        report.update(passed=True, actual_model_calls=calls, actual_preview=previews[0], result=result.model_dump(mode="json", by_alias=True),
            saved_plan=saved.model_dump(mode="json", by_alias=True),
            events=[event.model_dump(mode="json") for event in store.platform.events(project.id)],
            recorded_events=0, reviewed_labels=0, evaluations=0, deployment_id=None)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    report.update(elapsed_s=time.monotonic() - started, source_unchanged=source_identity(repo) == expected_hash)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_s", "source_unchanged")}), flush=True)
    if not report["passed"] or not report["source_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.workspace, args.output))
