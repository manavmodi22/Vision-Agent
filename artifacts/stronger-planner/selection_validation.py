"""Actual planner/model selection on existing public NVIDIA samples, not accuracy."""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.planner import plan  # noqa: E402
from engine.agent_state import AgentStateStore  # noqa: E402
from engine.datasets import DatasetClass, DatasetService  # noqa: E402
from engine.platform.planning_options import planning_options  # noqa: E402
from engine.runtime_identity import source_identity  # noqa: E402
from engine.service import WorkspaceService  # noqa: E402


async def main(label: str, expected_hash: str) -> None:
    assert label.replace("-", "").isalnum()
    output = ROOT / "artifacts/stronger-planner" / (label + ".json")
    assert not output.exists(), "Preserve earlier evidence; choose a new label"
    assert source_identity(ROOT) == expected_hash
    os.environ["VISION_APP_BINARY"] = str(ROOT / "app/.build/release/VisionApp")
    public_project = Path.home() / "Library/Application Support/VisionApp/projects/efee680b7955431b"
    source = json.loads((public_project / "project.json").read_text())
    paths = [Path(item) for item in source["media"][:3]]
    assert paths and all(path.is_file() for path in paths)
    workspace = ROOT / ".visionapp" / label
    service = WorkspaceService(workspace)
    project = service.create_project("Installed model selection on public warehouse samples", "custom")
    service.import_media(project.id, [str(path) for path in paths])
    datasets = DatasetService(service)
    manifest = datasets.manifest(project.id)
    datasets.save_classes(project.id, manifest.revision, [DatasetClass(id="person", name="person", color="#43C6AC")])
    options = planning_options(service, project.id)
    compatible = [option for option in options.eligible_models if "detection" in option.task_types and
                  (option.vocabulary == "open" or "person" in option.supported_classes)]
    expected_candidates = min(2, len(compatible))
    assert expected_candidates, options
    goal = ("Count people in these warehouse images and show boxes. Use confidence 0.2. "
            "Do not create events. " + ("Try two different compatible installed detector models with the same count MAE evaluation target." if expected_candidates == 2 else "Choose a compatible installed detector."))
    # The generic availability count above does not grant experimental scope.
    # Record the request-bound options actually relevant to this check.
    options = planning_options(service, project.id, request=goal)
    report = {"source_identity": expected_hash, "goal": goal, "project_id": project.id,
              "source_scope": "Three unreviewed public NVIDIA Warehouse 026 frames from the retained native sample project; no accuracy or deployment claim",
              "inputs": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths],
              "planning_options": options.model_dump(mode="json"), "expected_candidates": expected_candidates,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "native_binary_sha256": hashlib.sha256(Path(os.environ["VISION_APP_BINARY"]).read_bytes()).hexdigest(),
              "passed": False}
    started = monotonic()
    try:
        result = await plan(goal, "media", {"project_id": project.id,
            "mcp_data_dir": str(workspace), "use_case": "custom",
            "model_url": "http://127.0.0.1:1234/v1", "planner_model": "visionapp-planner"})
        store = AgentStateStore(service)
        operation = store.operation(project.id, result.operation_id)
        store.commit_plan(project.id, result.operation_id, result, goal)
        saved = store.platform.plans(project.id)[-1]
        selections = saved.model_selections
        calls = sum(call.kind == "llm" and call.status == "completed" for call in operation.calls)
        selected = {item.model_id for item in selections}
        assert len(result.candidates) == expected_candidates and len(selected) == expected_candidates
        assert calls > 0 and saved.planning_options_artifact_id
        assert len({json.dumps(candidate.eval.model_dump(mode="json"), sort_keys=True)
                    for candidate in result.candidates}) == 1
        for candidate in result.candidates:
            detector = next(block for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"})
            assert detector.params["classes"] == ["person"] and detector.params["min_conf"] == .2
            assert not any(block.type == "sink_event" for block in candidate.blocks)
        report.update(passed=True, actual_model_calls=calls, result=result.model_dump(mode="json", by_alias=True),
                      plan=saved.model_dump(mode="json", by_alias=True),
                      events=[event.model_dump(mode="json") for event in store.platform.events(project.id)],
                      stored_events=len(service.events(project.id)))
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    report.update(elapsed_s=monotonic() - started, source_unchanged=source_identity(ROOT) == expected_hash)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "elapsed_s", "source_unchanged")}), flush=True)
    if not report["passed"] or not report["source_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expected-hash", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.label, args.expected_hash))
