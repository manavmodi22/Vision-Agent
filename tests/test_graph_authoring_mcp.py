"""Actual MCP transport for composed graphs; deterministic software fixtures only."""
import hashlib
from pathlib import Path

import pytest

from agent.contracts import PlanDecision
from agent.decisions import plan_from_context
from agent.executor import execute_candidates
from agent.machine import AgentState
from agent.mcp_client import connect_tools
from engine.agent_state import AgentStateStore
from engine.service import WorkspaceService
from spec.models import RunResult
from spec.planning import PlanningOptions


def workspace_hashes(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


async def test_composed_crop_resize_count_crosses_actual_mcp_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "empty-model-cache"))
    monkeypatch.delenv("VISION_APP_BINARY", raising=False)
    workspace = tmp_path / "workspace"
    service = WorkspaceService(workspace)
    project = service.create_project("Composed MCP software fixture", "custom")
    service.demo(project.id)
    annotations_before = (service.root(project.id) / "annotations.json").read_bytes()
    store = AgentStateStore(service)
    brief = ("Count pallets in the left half of each image. Crop [0, 0, 0.5, 1], "
             "then resize to 320 by 200 pixels before detection. Use fixture-color-v1. "
             "Do not create events or send alerts. Use count_mae target 0.5.")

    async with connect_tools(str(workspace), AgentState()) as tools:
        # The obsolete host default must not override a saved per-node model binding.
        await tools.start_run(project.id, brief, "media", "owlv2-base-patch16")
        context = await tools.call("dataset_context", {"project_id": project.id})
        captured = PlanningOptions.model_validate(await tools.call("planning_options", {
            "project_id": project.id, "operation_id": tools.operation_id,
            "detection_constraint": "fixture-color-v1",
        }))
        assert captured.schema_version == "0.3" and captured.fixture_source
        option = next(item for item in captured.eligible_models if item.model_id == "fixture-color-v1")
        await tools.control("agent_record_options", {"snapshot_id": captured.snapshot_id})
        decision = PlanDecision.model_validate({"schema_version": "0.2",
            "message": "Deterministic graph transport test; no language-model quality claim",
            "graphs": [{"name": "Left-half fixture count", "metric": "count_mae", "target": 0.5,
                "nodes": [
                    {"id": "sample", "type": "frame_sample", "fps": 2},
                    {"id": "left", "type": "crop", "image": "$sample.frame", "box": [0, 0, 0.5, 1]},
                    {"id": "small", "type": "resize", "image": "$left.image", "width": 320, "height": 200},
                    {"id": "pallets", "type": "detect", "image": "$small.image",
                     "model_capability_id": option.capability_id, "model_reason": "Generated rectangle fixtures only",
                     "classes": ["pallet"], "min_confidence": 0.4},
                    {"id": "total", "type": "count_per_zone", "dets": "$pallets.dets", "include_unassigned": False},
                ]}],
        })
        await tools.control("agent_record_decision", {"decision": decision.model_dump(mode="json")})
        result = plan_from_context(decision, brief, "media", "owlv2-base-patch16", context, captured)
        await execute_candidates(tools, result, "media", "owlv2-base-patch16")
        result.operation_id, result.tool_calls = tools.operation_id, tools.state.budget.tool_calls
        await tools.control("agent_stage_plan", {"result": result.model_dump(mode="json", by_alias=True)})

    assert result.operation_id is not None
    store.commit_plan(project.id, result.operation_id, result, brief)
    operation = store.operation(project.id, result.operation_id)
    assert operation.status == "completed" and operation.decision == decision
    assert operation.planning_options == captured and operation.result == result
    assert not any(call.kind == "llm" for call in operation.calls)
    plans = store.platform.plans(project.id)
    assert len(plans) == 1
    saved = plans[0]
    assert saved.candidates == result.candidates == service.get_project(project.id).candidates
    assert saved.planning_options_artifact_id is not None
    assert store.platform.artifact_content(project.id, saved.planning_options_artifact_id).content == captured.model_dump(mode="json")
    assert [binding.model_dump(mode="json") for binding in saved.model_selections] == [{
        "candidate_index": 0, "block_id": "pallets", "capability_id": option.capability_id,
        "model_id": "fixture-color-v1", "adapter_id": option.adapter_id,
        "proposed_reason": "Generated rectangle fixtures only", "options_snapshot_id": captured.snapshot_id,
        "status": "proposed",
    }]
    candidate = saved.candidates[0]
    assert [(block.id, block.type, block.inputs) for block in candidate.blocks] == [
        ("sample", "frame_sample", {"frames": "$inputs.source"}),
        ("left", "crop", {"image": "$sample.frame"}),
        ("small", "resize", {"image": "$left.image"}),
        ("pallets", "detect", {"image": "$small.image"}),
        ("total", "count_per_zone", {"dets": "$pallets.dets"}),
    ]
    assert candidate.blocks[1].params == {"box": [0, 0, 0.5, 1]}
    assert candidate.blocks[2].params == {"width": 320, "height": 200}
    validation = [call for call in operation.calls if call.name == "pipeline_validate"]
    previews = [call for call in operation.calls if call.name == "pipeline_run"]
    assert len(validation) == len(previews) == 1
    assert validation[0].status == "completed" and validation[0].result == {"valid": True, "errors": []}
    preview = previews[0]
    assert preview.status == "completed" and preview.result is not None
    assert preview.request["spec"] == candidate.model_dump(mode="json", by_alias=True)
    actual = RunResult.model_validate(preview.result)
    # The first five generated frames have A+B counts 2,4,2,4,2. Whole-frame
    # counts would be 4,8,4,8,4, so this also detects a skipped crop at runtime.
    assert [frame.counts for frame in actual.frames] == [{"all": value} for value in (2, 4, 2, 4, 2)]
    for frame in actual.frames:
        assert not frame.events and not frame.comparisons
        assert len(frame.inferences) == 1
        evidence = frame.inferences[0]
        assert evidence.block_id == "pallets" and evidence.input_to_frame == (0, 0, 0.5, 1)
        assert evidence.result.input_size == (320, 200)
        assert evidence.result.identity.model_id == "fixture-color-v1"
        assert evidence.result.identity.capability_id == option.capability_id
        assert evidence.result.identity.identity_scope == "synthetic_code"
        assert all(detection.box[2] <= 0.5 for detection in frame.detections)

    before_replay = workspace_hashes(workspace)
    replay = store.replay(project.id, operation.id)
    assert replay.reproduced and replay.dry_run and not replay.effects_executed
    assert replay.result == result and replay.captured_model_calls == 0
    assert workspace_hashes(workspace) == before_replay
    assert not service.events(project.id) and not service.get_project(project.id).evaluations
    assert service.get_project(project.id).deployment_id is None
    assert (service.root(project.id) / "annotations.json").read_bytes() == annotations_before
