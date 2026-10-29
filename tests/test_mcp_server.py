import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.machine import AgentConflict, AgentState
from agent.mcp_client import connect_tools
from agent.templates import build_template
from engine.service import WorkspaceService


async def test_real_stdio_server_initializes_and_exposes_no_approval_tool(tmp_path: Path) -> None:
    parameters = StdioServerParameters(command=sys.executable,
                                       args=["-m", "mcp_server", "--data-dir", str(tmp_path)])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            catalog = await session.list_tools()
            names = {tool.name for tool in catalog.tools}
            assert {"blocks_list", "pipeline_validate", "pipeline_run", "eval_run", "events_query"} <= names
            assert not names & {"pipeline_deploy", "alerts_set", "delete_data"}
            result = await session.call_tool("block_schema", {"block_type": "rule"})
            assert not result.isError
            assert result.structuredContent is not None
            assert result.structuredContent["block"]["inputs"] == {"value": "counts"}


async def test_gated_mcp_client_dispatches_actual_catalog(tmp_path: Path) -> None:
    state = AgentState()
    state.confirm_brief(confirmed=True)
    async with connect_tools(str(tmp_path), state) as tools:
        result = await tools.call("blocks_list")
    assert isinstance(result["blocks"], list)
    assert state.budget.tool_calls == 1


async def test_proposed_spec_preview_is_real_and_agent_cannot_self_review(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("MCP fixture", "pallets")
    service.demo(project.id)
    candidate = build_template("pallets", "media", "fixture-color-v1")[0]
    parameters = StdioServerParameters(command=sys.executable,
                                       args=["-m", "mcp_server", "--data-dir", str(tmp_path)])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("pipeline_run", {
                "project_id": project.id, "spec": candidate.model_dump(mode="json", by_alias=True),
            })
            assert not result.isError
            assert result.structuredContent is not None
            assert len(result.structuredContent["frames"]) == 5
            candidate.inputs["source"].path = "/tmp"
            outside = await session.call_tool("pipeline_validate", {
                "project_id": project.id, "spec": candidate.model_dump(mode="json", by_alias=True),
            })
            assert outside.structuredContent is not None
            assert outside.structuredContent["valid"] is False
            labels = await session.call_tool("eval_create", {
                "project_id": project.id, "dataset": service.annotations(project.id).model_dump(mode="json"),
            })
            assert labels.isError


async def test_durable_mcp_begin_records_context_and_rejects_another_owner(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Durable MCP", "pallets")
    service.demo(project.id)
    first = AgentState()
    async with connect_tools(str(tmp_path), first) as tools:
        await tools.start_run(project.id, "Count pallets", "media", "fixture-color-v1")
        context = await tools.call("dataset_context", {"project_id": project.id})
        assert context["classes"] == ["pallet"]
        assert context["image_count"] == 16
        second = AgentState()
        async with connect_tools(str(tmp_path), second) as other:
            with pytest.raises(AgentConflict, match="Another agent operation"):
                await other.start_run(project.id, "Overwrite", "media", "fixture-color-v1")
        await tools.control("agent_run_fail", {"error": "Test finished without a model request"})
    from engine.agent_state import AgentStateStore

    record = AgentStateStore(service).runs(project.id)[0]
    assert record.status == "failed" and record.state.budget.tool_calls == 1
    assert record.calls[0].name == "dataset_context"
