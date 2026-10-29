"""Scripted deciders test real observation feedback; these are not A0 acceptance."""
import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from filelock import Timeout as LockTimeout
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from PIL import Image, ImageDraw

from agent.investigation import run_steps
from agent.investigation_client import InvestigationClient
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.models.fixture import PALETTE
from engine.service import WorkspaceService
from mcp_server.investigations import (
    execute_step,
    investigation_context,
    register_investigation_tools,
)
from spec.investigation import InvestigationBudget, NextAction


def test_probe_alternatives_require_discriminator_before_other_fields() -> None:
    from spec.inference_requests import BarcodeRequest, DetectionRequest, OcrRequest
    from spec.investigation import BarcodeProbeRequest, DetectionProbeRequest, OCRProbeRequest

    for variant, legacy in [(DetectionProbeRequest, DetectionRequest), (OCRProbeRequest, OcrRequest),
                            (BarcodeProbeRequest, BarcodeRequest)]:
        schema = variant.model_json_schema()
        assert next(iter(schema["properties"])) == schema["required"][0] == "task"
        assert "task" not in legacy.model_json_schema().get("required", [])
    schema = NextAction.model_json_schema()
    for name in ["DetectionProbeRequest", "OCRProbeRequest", "BarcodeProbeRequest"]:
        assert schema["$defs"][name]["required"][0] == "task"


class LocalSession:
    """Exercise registered MCP handlers/schema conversion without a socket server."""
    def __init__(self, server: FastMCP[None]) -> None:
        self.server = server

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        try:
            result = await self.server.call_tool(name, arguments)
            if isinstance(result, tuple):
                return CallToolResult(content=result[0], structuredContent=result[1])
            if isinstance(result, dict):
                return CallToolResult(content=[], structuredContent=result)
            return CallToolResult(content=list(result))
        except Exception as error:
            return CallToolResult(isError=True, content=[TextContent(type="text", text=str(error))])


def workspace(tmp_path: Path, budget: InvestigationBudget | None = None, object_present: bool = True) -> tuple[InvestigationStore, str, str, InvestigationClient]:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("A0 loop software fixture", "custom")
    path = tmp_path / "source.png"
    image = Image.new("RGB", (80, 60), "black")
    if object_present:
        ImageDraw.Draw(image).rectangle((15, 10, 49, 39), fill=PALETTE["pallet"])
    image.save(path)
    service.import_media(project.id, [str(path)])
    project = service.get_project(project.id)
    project.fixture, project.synthetic = True, True
    project.data_origin = "Generated color rectangles for software loop tests"
    service.repository.save(project)
    store = InvestigationStore(service)
    task = store.create(project.id, "Investigate this image using available local evidence", budget)
    server: FastMCP[None] = FastMCP("investigation integration test")
    register_investigation_tools(server, store)
    client = InvestigationClient(cast(ClientSession, LocalSession(server)), project.id, task.id)
    return store, project.id, task.id, client


def reply(context: dict[str, Any], action: dict[str, Any], references: list[str] | None = None) -> dict[str, Any]:
    return {"decision": {"type": "next_action", "state_revision": context["state"]["revision"],
        "decision_summary": "Scripted integration decider; no real language-model reasoning claim",
        "based_on_observation_ids": references or [], "action": action}}


async def test_owned_probe_worker_rechecks_revoked_fixture_project_permission(tmp_path: Path) -> None:
    from engine.eval.usage import read_usage

    store, project, task, _ = workspace(tmp_path)
    capability = await execute_step(store, project, task,
        capture(store, project, task, {"type": "inspect_capability", "capability_id": "model.fixture-color-v1"}))
    assert capability.payload["model_view"]["probe_eligible"] is True
    source = (await execute_step(store, project, task, capture(store, project, task, {"type": "inspect_media"}))).payload["items"][0]
    state = store.service.get_project(project)
    state.fixture = False
    assert state.synthetic is True  # Synthetic provenance is not fixture permission.
    store.service.repository.save(state)
    action = {"type": "run_probe", "capability_id": "model.fixture-color-v1",
        "inspected_descriptor_hash": capability.payload["descriptor"]["descriptor_hash"],
        "media_id": source["media_id"], "source_sha256": source["source_sha256"],
        "request": {"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}}
    observed = await execute_step(store, project, task, capture(store, project, task, action))
    assert observed.status == "failed" and observed.payload["executed"] is False
    assert "nonfixture" in observed.error["message"]
    assert not read_usage(store.service.root(project)).uses
    assert not (store.root(project, task) / "artifacts").exists()


async def test_action_contracts_are_supplied_in_actual_model_context(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path)

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        context = request["context"]
        assert request["schema"]["required"][0] == "type"
        assert "based_on_observation_ids" in request["schema"]["required"]
        assert list(context)[:3] == ["action_contracts", "workflow_capabilities", "planner_modality"]
        assert "run_probe" in context["action_contracts"]
        assert "media_id" in context["action_contracts"]["run_probe"]["required_fields"]
        assert "media_ids" in context["action_contracts"]["inspect_media"]["fields"]
        assert context["state"]["stage"] == "investigating" and not store.actions(project, task)
        operators = {row["type"]: row for row in context["workflow_capabilities"]["operators"]}
        assert operators["crop"]["inputs"] == {"image": "image"}
        assert operators["resize"]["outputs"] == {"image": "image"}
        assert "node_contracts" not in context
        assert "successful probes do not automatically" in context["action_contracts"]["prepare_workflow"]["description"]
        return reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "Protocol test only"})

    result = await run_steps(client, decide, "scripted-protocol-test")
    assert result.status == "inconclusive"
    captured = store.model_calls(project, task)[0]
    assert "action_contracts" in captured.context["context"]


@pytest.mark.parametrize("object_present", [True, False])
async def test_actual_probe_observation_changes_next_selected_action(tmp_path: Path, object_present: bool) -> None:
    store, project, task, client = workspace(tmp_path, object_present=object_present)
    contexts: list[dict[str, Any]] = []
    capability: dict[str, Any] = {}
    media: dict[str, Any] = {}

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        context = request["context"]
        contexts.append(context)
        observations = context["observations"]
        if not observations:
            return reply(context, {"type": "inspect_capability", "capability_id": "model.fixture-color-v1"})
        latest = observations[-1]
        if latest["result_type"] == "inspect_capability":
            capability.update(latest["payload"]["descriptor"])
            return reply(context, {"type": "inspect_media"}, [latest["id"]])
        if latest["result_type"] == "inspect_media":
            media.update(latest["payload"]["items"][0])
            confidence = 1.0
        elif latest["result_type"] == "run_probe" and latest["payload"]["request"]["min_conf"] == 1.0:
            assert latest["payload"]["executed"] is True
            assert latest["payload"]["total_items"] == 0
            confidence = .4  # Chosen only after receiving the actual empty observation.
        elif latest["result_type"] == "run_probe":
            if latest["payload"]["total_items"]:
                return reply(context, {"type": "inspect_observation", "observation_id": latest["id"], "view": "geometry"}, [latest["id"]])
            return reply(context, {"type": "ask_user", "question": "What visible evidence should this empty result be checked against?"}, [latest["id"]])
        else:
            assert latest["result_type"] == "inspect_observation" and latest["payload"]["items"]
            return reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "The software fixture produced geometry, but application correctness remains unverified", "evidence_ids": [latest["id"]]}, [latest["id"]])
        return reply(context, {"type": "run_probe", "capability_id": capability["id"],
            "inspected_descriptor_hash": capability["descriptor_hash"], "media_id": media["media_id"],
            "source_sha256": media["source_sha256"], "request": {"task": "detection", "model_id": "fixture-color-v1",
            "classes": ["pallet"], "min_conf": confidence}}, [latest["id"]])

    result = await run_steps(client, decide, "scripted-observation-dependent-decider")
    assert result.status == ("inconclusive" if object_present else "awaiting_input")
    observations = store.observations(project, task)
    probes = [item for item in observations if item.result_type == "run_probe"]
    assert len(probes) == 2 and all(item.status == "completed" for item in probes)
    assert probes[0].payload["total_items"] == 0
    assert probes[1].payload["total_items"] == int(object_present)
    actions = store.actions(project, task)
    second = [item for item in actions if item.action.type == "run_probe"][1]
    assert second.decision.based_on_observation_ids == [probes[0].id]
    assert any(probes[0].id in item["visible_observation_ids"] for item in contexts)
    assert result.budget.probes == 2 and not store.service.events(project)
    assert not store.service.get_project(project).candidates


async def test_malformed_response_retains_raw_error_feedback_for_next_decision(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path)
    count = 0
    malformed = {"raw_output": "actual malformed scripted output", "decision": None}

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal count
        count += 1
        if count == 1:
            return malformed
        context = request["context"]
        assert "Invalid next-action" in context["last_model_error"]
        assert not context["recent_actions"]
        return reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "Stopped after inspecting actual validation feedback"})

    result = await run_steps(client, decide, "scripted-malformed-output-test")
    assert result.status == "inconclusive"
    calls = store.model_calls(project, task)
    assert calls[0].response == malformed and calls[0].status == "failed" and calls[0].error
    assert len(store.actions(project, task)) == 1 and result.budget.model_calls == 2


async def test_exhausted_model_budget_returns_persisted_terminal_state(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path, InvestigationBudget(max_model_calls=1))

    async def invalid(_request: dict[str, Any]) -> dict[str, Any]:
        return {"decision": None, "raw_output": "invalid output consumes budget"}

    state = await run_steps(client, invalid, "scripted-exhaustion-test")
    assert state.status == "inconclusive" and "budget exhausted" in (state.stop_reason or "")
    assert state == store.get(project, task)
    assert state.budget.model_calls == 1 and not store.actions(project, task)


async def test_exhausted_action_budget_returns_persisted_terminal_state(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path, InvestigationBudget(max_actions=1))

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        context = request["context"]
        return reply(context, {"type": "inspect_media"} if not context["observations"] else
                     {"type": "finish", "outcome": "inconclusive", "summary": "No budget for another action"})

    state = await run_steps(client, decide, "scripted-action-exhaustion-test")
    assert state.status == "inconclusive" and "action budget exhausted" in (state.stop_reason or "")
    assert state.budget.actions == 1 and len(store.observations(project, task)) == 1


async def test_model_cancellation_is_recorded_without_dispatching_any_action(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path)
    entered = asyncio.Event()

    async def delayed(_request: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    running = asyncio.create_task(run_steps(client, delayed, "scripted-cancellation-test"))
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    calls = store.model_calls(project, task)
    assert len(calls) == 1 and calls[0].status == "failed" and "cancelled" in (calls[0].error or "")
    assert not store.actions(project, task) and store.get(project, task).budget.model_calls == 1


def capture(store: InvestigationStore, project: str, task: str, action: dict[str, Any]) -> NextAction:
    context = investigation_context(store, project, task)
    response = reply(context, action)
    call = store.start_model_call(project, task, {"context": context}, "scripted-transport-test")
    store.finish_model_call(project, task, call.id, response)
    return NextAction.model_validate(response["decision"])


async def test_large_actual_probe_keeps_typed_summary_visible_to_next_model(tmp_path: Path) -> None:
    store, project, task, _ = workspace(tmp_path)
    image = Image.new("RGB", (320, 80), "black")
    draw = ImageDraw.Draw(image)
    for index in range(8):
        draw.rectangle((index * 40 + 5, 10, index * 40 + 25, 40), fill=PALETTE["pallet"])
    image.save(store.service.get_project(project).media[0])
    capability = await execute_step(store, project, task,
        capture(store, project, task, {"type": "inspect_capability", "capability_id": "model.fixture-color-v1"}))
    media = await execute_step(store, project, task, capture(store, project, task, {"type": "inspect_media"}))
    source = media.payload["items"][0]
    probe = {"type": "run_probe", "capability_id": "model.fixture-color-v1",
        "inspected_descriptor_hash": capability.payload["descriptor"]["descriptor_hash"],
        "media_id": source["media_id"], "source_sha256": source["source_sha256"],
        "request": {"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}}
    observation = await execute_step(store, project, task, capture(store, project, task, probe))
    assert observation.payload["total_items"] == 8 and observation.payload["executed"] is True
    projected = investigation_context(store, project, task)["observations"][-1]["payload"]
    assert projected["total_items"] == 8 and projected["executed"] is True
    assert projected["request"]["min_conf"] == .4
    assert projected.get("items"), "Agent needs bounded typed values, not a cut JSON string"


async def test_execution_rejects_action_that_differs_from_captured_model_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_server.investigations as module
    store, project, task, _ = workspace(tmp_path)
    selected = capture(store, project, task, {"type": "inspect_media"})
    changed = selected.model_copy(update={"decision_summary": "Uncaptured action mutation"})
    monkeypatch.setattr(module.InvestigationTools, "execute", lambda *_args: pytest.fail("Unauthorized action executed"))
    with pytest.raises(InvestigationConflict, match="differs"):
        await execute_step(store, project, task, changed)
    assert not store.actions(project, task) and not store.observations(project, task)


def slow_probe_action() -> dict[str, Any]:
    return {"type": "run_probe", "capability_id": "model.fixture-color-v1",
        "inspected_descriptor_hash": "a" * 64, "media_id": "test-media", "source_sha256": "b" * 64,
        "request": {"task": "detection", "model_id": "fixture-color-v1", "classes": ["pallet"], "min_conf": .4}}


async def test_cancelled_action_cannot_commit_a_late_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_server.investigations as module
    store, project, task, _ = workspace(tmp_path)
    selected = capture(store, project, task, slow_probe_action())
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(*_args: Any) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"status": "completed", "payload": {"late": True}}

    monkeypatch.setattr(module, "run_owned_probe", delayed)
    running = asyncio.create_task(execute_step(store, project, task, selected))
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    release.set()
    observation = store.observations(project, task)[0]
    assert observation.status == "interrupted" and not observation.payload
    receipt = store.actions(project, task)[0]
    with pytest.raises(InvestigationConflict):
        store.complete_action(project, task, receipt.id, {"late": True})
    assert len(store.observations(project, task)) == 1 and store.get(project, task).budget.probes == 1


async def test_cancel_cleanup_does_not_replace_an_already_stopped_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_server.investigations as module
    store, project, task, _ = workspace(tmp_path)
    selected = capture(store, project, task, slow_probe_action())
    entered = asyncio.Event()

    async def delayed(*_args: Any) -> dict[str, Any]:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(module, "run_owned_probe", delayed)
    running = asyncio.create_task(execute_step(store, project, task, selected))
    await asyncio.wait_for(entered.wait(), 2)
    store.stop(project, task, "Explicit user cancellation", "cancelled")
    original = store.observations(project, task)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert store.get(project, task).status == "cancelled"
    assert store.observations(project, task) == original


async def test_concurrent_duplicate_dispatch_executes_at_most_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_server.investigations as module
    store, project, task, _ = workspace(tmp_path)
    selected = capture(store, project, task, slow_probe_action())
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def delayed(*_args: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"status": "completed", "payload": {"test_barrier": True}}

    monkeypatch.setattr(module, "run_owned_probe", delayed)
    first = asyncio.create_task(execute_step(store, project, task, selected))
    await asyncio.wait_for(entered.wait(), 2)
    with pytest.raises((LockTimeout, InvestigationConflict)):
        await execute_step(store, project, task, selected)
    release.set()
    await first
    assert calls == 1 and len(store.observations(project, task)) == 1


async def test_model_selected_workflow_stage_previews_in_worker_before_draft_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scripted protocol integration, not live-agent acceptance or model-quality evidence."""
    import mcp_server.investigations as module
    from agent.templates import build_template
    from spec.investigation import WorkflowDecision

    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Workflow loop software fixture", "custom")
    service.demo(project.id)  # Marks these generated sources eligible for the fixture model.
    original_candidates = build_template("pallets", "media", "fixture-color-v1")
    service.save_candidates(project.id, original_candidates, "Existing project candidate must survive investigation")
    store = InvestigationStore(service)
    task = store.create(project.id, "Create a draft from a software fixture and inspect its actual preview")
    server: FastMCP[None] = FastMCP("workflow loop integration test")
    register_investigation_tools(server, store)
    client = InvestigationClient(cast(ClientSession, LocalSession(server)), project.id, task.id)
    root = service.root(project.id)
    before = {name: (root / name).read_bytes() for name in ("project.json", "annotations.json")}
    worker_actions: list[str] = []
    real_worker = module.run_owned_probe

    async def observe_real_worker(*args: Any, **kwargs: Any) -> dict[str, object]:
        worker_actions.append(args[4].type)
        return await real_worker(*args, **kwargs)  # Execute the real subprocess and inference.

    monkeypatch.setattr(module, "run_owned_probe", observe_real_worker)
    media: dict[str, Any] = {}
    preview_seen: dict[str, Any] = {}
    schema_stages: list[str] = []

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        context = request["context"]
        schema_stages.append(request["schema"]["properties"]["type"]["const"])
        observations = context["observations"]
        if not observations:
            return reply(context, {"type": "inspect_capability", "capability_id": "model.fixture-color-v1"})
        latest = observations[-1]
        selected = context.get("selected_workflow")
        if selected is not None and selected["status"] == "available":
            # The saved draft has its own persistent context, separate from
            # recent experimental observations (and without duplicate values).
            latest = {"id": selected["preview_observation_id"], "status": selected["preview_status"],
                      "result_type": "construct_workflow", "payload": selected}
        assert latest["status"] == "completed", latest.get("error")
        if latest["result_type"] == "inspect_capability":
            return reply(context, {"type": "inspect_media", "limit": 1}, [latest["id"]])
        if latest["result_type"] == "inspect_media":
            media.update(latest["payload"]["items"][0])
            return reply(context, {"type": "prepare_workflow", "evidence_ids": [latest["id"]],
                "summary": "Construct and measure a fixture draft using the inspected development image"}, [latest["id"]])
        if latest["result_type"] == "prepare_workflow":
            assert context["state"]["stage"] == "workflow"
            assert request["schema"]["properties"]["type"]["const"] == "workflow_decision"
            assert request["schema"]["required"][0] == "type"
            assert "based_on_observation_ids" in request["schema"]["required"]
            assert list(context)[:3] == ["action_contracts", "node_contracts", "planner_modality"]
            assert "workflow_capabilities" not in context
            assert {"frame_sample", "crop", "resize", "detect", "count_per_zone", "rule", "sink_event"} <= set(context["node_contracts"])
            assert "model_capability_id" in context["node_contracts"]["detect"]["required_fields"]
            assert "dets" in context["node_contracts"]["detect"]["outputs"]
            choice = WorkflowDecision.model_validate({"type": "workflow_decision",
                "state_revision": context["state"]["revision"],
                "decision_summary": "Scripted choice of a real executable fixture graph",
                "based_on_observation_ids": [latest["id"]],
                "action": {"type": "construct_workflow", "media_ids": [media["media_id"]],
                    "evidence_ids": [latest["id"]], "graph": {"name": "Task-owned fixture draft",
                        "metric": "count_mae", "target": .5, "nodes": [
                            {"type": "frame_sample", "id": "sample", "fps": 1},
                            {"type": "crop", "id": "crop", "image": "$sample.frame", "box": [0, 0, .5, 1]},
                            {"type": "resize", "id": "resize", "image": "$crop.image", "width": 320, "height": 400},
                            {"type": "detect", "id": "det", "image": "$resize.image", "classes": ["pallet"],
                             "min_confidence": .4, "model_capability_id": "model.fixture-color-v1",
                             "model_reason": "Synthetic software verification only"},
                            {"type": "count_per_zone", "id": "count", "dets": "$det.dets", "include_unassigned": False},
                            {"type": "rule", "id": "rule", "counts": "$count.counts", "operator": ">=", "threshold": 1, "hold_seconds": 0},
                            {"type": "sink_event", "id": "event", "event": "$rule.event"},
                        ]}}})
            return {"decision": choice.model_dump(mode="json")}
        assert latest["result_type"] == "construct_workflow"
        assert context["state"]["stage"] == "investigating"
        assert request["schema"]["properties"]["type"]["const"] == "next_action"
        payload = latest["payload"]
        assert payload["executed"] is True and payload["validated"] is True and payload["preview_success"] is True
        assert payload["preview_media_ids"] == [media["media_id"]]
        assert payload["spec_hash"] == payload["preview_spec_hash"]
        frame = payload["preview"]["frames"][0]
        assert frame["source_image_sha256"] == media["source_sha256"]
        assert frame["counts"]["all"] > 0 and frame["events"]
        inference = frame["inferences"][0]
        assert inference["input_to_frame"] == [0, 0, .5, 1]
        assert inference["result"]["input_size"] == [320, 400]
        assert inference["result"]["identity"]["identity_scope"] == "synthetic_code"
        preview_seen.update(latest)
        return reply(context, {"type": "finish", "outcome": "draft_ready",
            "workflow_revision_id": payload["workflow_revision_id"], "evidence_ids": [latest["id"]],
            "summary": "A fixture draft executed successfully; real-world accuracy and deployment remain unapproved"}, [latest["id"]])

    state = await run_steps(client, decide, "scripted-workflow-protocol-test")
    assert state.status == "draft_ready", state.stop_reason
    assert schema_stages == ["next_action", "next_action", "next_action", "workflow_decision", "next_action"]
    assert worker_actions == ["construct_workflow"]
    assert state.preview_observation_id == preview_seen["id"]
    assert state.selected_workflow_revision == preview_seen["payload"]["workflow_revision_id"]
    observations = store.observations(project.id, task.id)
    assert [row.result_type for row in observations] == ["inspect_capability", "inspect_media", "prepare_workflow", "construct_workflow", "finish"]
    assert all(row.status == "completed" for row in observations)
    construction = store.actions(project.id, task.id)[3]
    assert isinstance(construction.decision, WorkflowDecision)
    finish = store.actions(project.id, task.id)[4]
    assert finish.action.evidence_ids == [state.preview_observation_id]
    captured = store.model_calls(project.id, task.id)
    assert captured[3].context["schema"]["properties"]["type"]["const"] == "workflow_decision"
    assert state.preview_observation_id in captured[4].visible_observation_ids
    assert before == {name: (root / name).read_bytes() for name in before}
    assert service.get_project(project.id).candidates == original_candidates
    assert service.get_project(project.id).approval_scope is None
    assert not service.review(project.id) and not service.events(project.id)
    assert not (root / "deployment.json").exists()
    assert (store.root(project.id, task.id) / "workflows" / state.selected_workflow_revision / "version.json").exists()


def test_model_visible_docs_include_parameter_constraints_and_only_legal_actions() -> None:
    from agent.investigation import action_contracts, node_contracts, workflow_action_contracts

    actions = action_contracts()
    assert set(actions) == {"discover_capabilities", "inspect_capability", "inspect_media", "run_probe",
                           "inspect_observation", "prepare_workflow", "ask_user", "finish"}
    discovery = actions["discover_capabilities"]["fields"]
    assert discovery["kind"]["anyOf"][0]["enum"] == ["model", "tool"]
    assert discovery["limit"]["minimum"] == 1 and discovery["limit"]["maximum"] == 8
    probe = actions["run_probe"]
    assert probe["fields"]["request"]["discriminator"]["propertyName"] == "task"
    assert {"CropTransform", "ResizeTransform", "DetectionProbeRequest", "OCRProbeRequest", "BarcodeProbeRequest"} <= set(probe["$defs"])
    assert probe["$defs"]["ResizeTransform"]["properties"]["width"]["maximum"] == 8192
    assert probe["fields"]["transforms"]["maxItems"] == 4
    workflow = workflow_action_contracts()
    assert set(workflow) == {"construct_workflow"}
    graph = workflow["construct_workflow"]["fields"]["graph"]
    assert set(graph["required"]) == {"name", "nodes", "metric", "target"}
    assert graph["properties"]["nodes"]["maxItems"] == 16
    assert "count_mae" in graph["properties"]["metric"]["enum"]
    nodes = node_contracts()
    assert nodes["count_per_zone"]["fields"]["include_unassigned"]["type"] == "boolean"
    assert nodes["rule"]["fields"]["operator"]["enum"] == [">=", "<=", ">", "<", "==", "!="]
    assert nodes["detect"]["fields"]["image"]["pattern"].startswith("^")
    assert nodes["detect"]["fields"]["min_confidence"]["maximum"] == 1
    assert "dets" in nodes["detect"]["outputs"]


async def test_response_grammar_size_is_not_counted_as_model_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, project, task, client = workspace(tmp_path)
    original = NextAction.model_json_schema

    def large_grammar(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return original(*args, **kwargs) | {"description": "Grammar metadata only. " * 2000}

    monkeypatch.setattr(NextAction, "model_json_schema", large_grammar)

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        assert len(request["schema"]["description"]) > 26000
        assert "Grammar metadata only" not in str(request["context"])
        return reply(request["context"], {"type": "finish", "outcome": "inconclusive", "summary": "Protocol test ended"})

    state = await run_steps(client, decide, "scripted-grammar-budget-test")
    assert state.status == "inconclusive" and state.stop_reason == "Protocol test ended"
    assert len(store.model_calls(project, task)) == 1


def test_prompt_transport_reserves_output_budget() -> None:
    from agent.investigation import MAX_PROMPT_AND_OUTPUT_CHARS, prompt_transport_fits

    assert MAX_PROMPT_AND_OUTPUT_CHARS == 65536
    # Retained evidence can exceed the former graph-only transport budget, but
    # construction still needs its larger output reservation within the bound.
    context = {"evidence": "x" * 52000}
    assert prompt_transport_fits(context, 1400)
    assert not prompt_transport_fits(context, 2600)
    assert prompt_transport_fits({"evidence": "x" * 19000}, 2600)
    assert not prompt_transport_fits({"evidence": "x" * 65536}, 1400)


@pytest.mark.parametrize("reported_window,context_window,input_tokens,output_tokens,effective_window,allowed", [
    (8192, 8192, 5000, 2600, 8192, True),
    (8192, 8192, 5500, 2600, 8192, False),
    (4096, 4096, 2000, 2600, 4096, False),
    (8192, 8192, 6936, 1400, 8192, False),  # Actual Run5 request remains too large for 8K.
    (16384, 16384, 6936, 1400, 16384, True),
    (16384, 16384, 12000, 2600, 16384, True),  # A larger workflow with retained tool evidence.
    (16384, 8192, 6936, 1400, 8192, False),  # Actual active window beats larger advertised metadata.
    (8192, 16384, 6936, 1400, 8192, False),  # Keep the lower advertised bound too.
    (None, 16384, 6936, 1400, 16384, True),  # Verified props need no unknown-backend fallback.
    (32768, 32768, 14856, 1400, 16384, True),  # Exactly the local ceiling including margin.
    (32768, 32768, 14857, 1400, 16384, False),
])
async def test_live_budget_uses_selected_llama_template_tokens_and_active_context(
    reported_window: int | None, context_window: int, input_tokens: int,
    output_tokens: int, effective_window: int, allowed: bool,
) -> None:
    import httpx

    from agent.investigation import verify_prompt_budget

    calls: list[str] = []
    messages = [{"role": "system", "content": "System instructions"}, {"role": "user", "content": "Actual context"}]

    def handle(request: httpx.Request) -> httpx.Response:
        import json
        calls.append(request.url.path)
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [
                {"id": "other", "owned_by": "llamacpp", "meta": {"n_ctx": 100000}},
                {"id": "chosen", "owned_by": "llamacpp", "meta": {"n_ctx": reported_window}},
            ]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_alias": "chosen", "default_generation_settings": {"n_ctx": context_window}})
        if request.url.path == "/apply-template":
            body = json.loads(request.content)
            assert body["messages"] == messages and body["model"] == "chosen"
            assert "schema" not in body
            return httpx.Response(200, json={"prompt": "Actual rendered chat template"})
        assert request.url.path == "/tokenize"
        assert json.loads(request.content) == {"content": "Actual rendered chat template", "add_special": False, "parse_special": True}
        return httpx.Response(200, json={"tokens": [12] * input_tokens})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        if allowed:
            result = await verify_prompt_budget(client, "http://localhost/v1", "chosen", messages, output_tokens)
            assert result["input_tokens"] == input_tokens and result["context_verified"] is True
            assert result["backend_context_tokens"] == context_window and result["margin_tokens"] == 128
            assert result["effective_context_tokens"] == effective_window
        else:
            with pytest.raises(ValueError, match=f"exceeds {effective_window} tokens"):
                await verify_prompt_budget(client, "http://localhost/v1", "chosen", messages, output_tokens)
    assert calls == ["/v1/models", "/props", "/apply-template", "/tokenize"]


@pytest.mark.parametrize("reported_window,effective_window", [
    (None, 8192), (False, 8192), (0, 8192), ("16384", 8192),
    (4096, 4096), (8192, 8192), (16384, 16384), (32768, 16384),
])
async def test_generic_backend_budget_is_explicit_estimate_without_llama_dependency(
    reported_window: int | str | None, effective_window: int,
) -> None:
    import httpx

    from agent.investigation import verify_prompt_budget

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "generic-local-model", "owned_by": "local-server",
                                                 "meta": {"n_ctx": reported_window}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await verify_prompt_budget(client, "http://localhost/v1", "generic-local-model",
                                           [{"role": "user", "content": "Small actual context"}], 1400)
        assert result["mode"] == "conservative_estimate" and result["context_verified"] is False
        assert result["effective_context_tokens"] == effective_window
        assert "not an exact count" in result["limitation"]
        if not isinstance(reported_window, int) or isinstance(reported_window, bool) or reported_window <= 0:
            assert result["backend_context_tokens"] is None
            assert "8192-token fallback budget" in result["limitation"]
        else:
            assert result["backend_context_tokens"] == reported_window
        large_messages = [{"role": "user", "content": "x" * (6936 * 2)}]
        if effective_window >= 16384:
            larger = await verify_prompt_budget(client, "http://localhost/v1", "generic-local-model", large_messages, 1400)
            assert larger["estimated_input_tokens"] == 6936 and larger["context_verified"] is False
        else:
            with pytest.raises(ValueError, match=f"exceeds {effective_window} tokens"):
                await verify_prompt_budget(client, "http://localhost/v1", "generic-local-model", large_messages, 1400)
        with pytest.raises(ValueError, match=f"exceeds {effective_window} tokens"):
            await verify_prompt_budget(client, "http://localhost/v1", "generic-local-model",
                                       [{"role": "user", "content": "x" * 32768}], 1400)


def test_ocr_language_schema_matches_existing_validation_and_defaults() -> None:
    from pydantic import ValidationError

    from engine.capabilities.models import _fixture
    from engine.investigations.tools import descriptor
    from spec.inference_requests import OcrRequest
    from spec.investigation import OCRProbeRequest

    for kind in (OcrRequest, OCRProbeRequest):
        field = kind.model_json_schema()["properties"]["languages"]
        assert field["minItems"] == field["maxItems"] == 1
        assert field["items"] == {"type": "string", "const": "en-US"}
        assert kind(task="ocr").languages == ["en-US"]
        for languages in (["en"], [], ["en-US", "en-US"], ["EN-US"]):
            with pytest.raises(ValidationError) as failed:
                kind(task="ocr", languages=languages)
            error = failed.value.errors()[0]
            assert error["loc"] == ("languages",) and error["type"] == "value_error"
            assert error["msg"] == "Value error, The supported OCR request language is en-US"
    capability = _fixture().model_copy(update={"id": "model.apple-vision", "task_types": ["ocr"]})
    advertised = descriptor(capability)["probe_request_schemas"][0]["properties"]["languages"]
    assert advertised["minItems"] == advertised["maxItems"] == 1
    assert advertised["items"]["const"] == "en-US"


async def test_missing_raw_provenance_is_retained_and_retried_without_executing(tmp_path: Path) -> None:
    store, project, task, client = workspace(tmp_path)
    omitted: dict[str, Any] = {}
    calls = 0

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        context = request["context"]
        assert "based_on_observation_ids" in request["schema"]["required"]
        assert request["schema"]["required"].index("based_on_observation_ids") < request["schema"]["required"].index("action")
        proposed = reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "Protocol test ended"})
        if calls == 1:
            proposed["decision"].pop("based_on_observation_ids")
            omitted.update(proposed)
            assert NextAction.model_validate(proposed["decision"]).based_on_observation_ids == []
            return proposed
        assert "based_on_observation_ids" in context["last_model_error"]
        assert context["recent_actions"] == []
        return proposed

    final = await run_steps(client, decide, "scripted-raw-provenance-test")
    assert final.status == "inconclusive" and calls == 2
    captured = store.model_calls(project, task)
    assert captured[0].response == omitted and captured[0].status == "failed"
    assert "based_on_observation_ids" not in captured[0].response["decision"]
    assert captured[1].response["decision"]["based_on_observation_ids"] == []
    assert len(store.actions(project, task)) == 1
