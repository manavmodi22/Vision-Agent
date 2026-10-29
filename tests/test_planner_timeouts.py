"""Transport and total deadlines stay finite without contacting a model server."""
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx2
import pytest
from openai import APITimeoutError, DefaultAsyncHttpxClient
from pydantic import JsonValue
from pydantic_ai.exceptions import ModelAPIError

import agent.planner as planner
from agent.contracts import PlanResult
from agent.machine import AgentState
from agent.mcp_client import MCPTools


class CapturedTools:
    def __init__(self) -> None:
        self.receipt = json.loads((Path(__file__).parent / "fixtures/planner-context-warehouse.json").read_text())
        self.operation_id = "timeout-regression"
        self.state = AgentState()
        self.controls: list[str] = []
        self.capture_errors: list[str | None] = []

    async def call(self, name: str, arguments: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.receipt["tools"][name])

    async def control(self, name: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        self.controls.append(name)
        return {}

    async def capture_start(self, name: str, request: dict[str, JsonValue]) -> SimpleNamespace:
        return SimpleNamespace(id="request")

    async def capture_finish(self, call_id: str, result: dict[str, JsonValue] | None,
                             error: str | None = None) -> None:
        self.capture_errors.append(error)

    async def start_run(self, project_id: str, brief: str, source_path: str, detector_model: str) -> None:
        pass


async def test_initial_request_has_bounded_timeout_and_no_transport_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = CapturedTools()
    requests: list[httpx2.Request] = []
    clients: list[DefaultAsyncHttpxClient] = []

    def timeout_transport(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.extensions["timeout"] == {"connect": 4, "read": 150, "write": 15, "pool": 4}
        raise httpx2.ReadTimeout("Simulated slow local generation", request=request)

    def client(*, trust_env: bool, timeout: httpx2.Timeout) -> DefaultAsyncHttpxClient:
        assert trust_env is False
        instance = DefaultAsyncHttpxClient(trust_env=trust_env, timeout=timeout,
                                          transport=httpx2.MockTransport(timeout_transport))
        clients.append(instance)
        return instance

    monkeypatch.setattr(planner, "DefaultAsyncHttpxClient", client)
    with pytest.raises(ModelAPIError, match="Request timed out") as caught:
        await planner._generate(tools.receipt["brief"], "media",
            {"project_id": tools.receipt["project_id"], "use_case": "custom"},
            cast(MCPTools, tools), "http://127.0.0.1:1234/v1", "no-live-model")
    assert isinstance(caught.value.__cause__, APITimeoutError)
    assert len(requests) == 1
    assert clients[0].is_closed
    assert tools.capture_errors == ["Request timed out."]
    assert tools.controls == ["agent_record_options", "agent_record_skills"]


async def test_total_planning_deadline_still_cancels_without_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = CapturedTools()
    cancelled = False
    real_timeout = asyncio.timeout
    deadlines: list[float | None] = []

    def scaled_timeout(seconds: float | None) -> asyncio.Timeout:
        deadlines.append(seconds)
        return real_timeout(0.01)

    @asynccontextmanager
    async def connected(data_dir: str, state: AgentState) -> AsyncIterator[MCPTools]:
        yield cast(MCPTools, tools)

    async def healthy(url: str, model: str) -> None:
        pass

    async def slow(brief: str, source_path: str, settings: dict[str, JsonValue],
                   tools: MCPTools, url: str, model_name: str) -> PlanResult:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
        raise AssertionError("A cancelled request must not return a plan")

    monkeypatch.setattr(asyncio, "timeout", scaled_timeout)
    monkeypatch.setattr(planner, "connect_tools", connected)
    monkeypatch.setattr(planner, "check_model", healthy)
    monkeypatch.setattr(planner, "_generate", slow)
    with pytest.raises(planner.PlannerError, match="wall-clock budget"):
        await planner.plan("Count people", "media", {
            "project_id": "timeout-project", "mcp_data_dir": "/unused",
            "planner_model": "no-live-model", "model_url": "http://127.0.0.1:1234/v1"})
    assert deadlines == [180]
    assert cancelled
    assert "agent_stage_plan" not in tools.controls
