"""Real MCP transport. No engine imports or direct project/model access."""

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import JsonValue, TypeAdapter

from agent.evidence_state import EvidenceOperation
from agent.machine import AgentConflict, AgentError, AgentState
from agent.state_contracts import (
    AgentOperation,
    BeginOperationResult,
    CapturedCall,
    ToolDispatchResult,
)
from spec.skills import SkillReference

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class MCPTools:
    def __init__(self, session: ClientSession, state: AgentState) -> None:
        self.session = session
        self.state = state
        self.project_id = ""
        self.operation_id = ""
        self.query_id = ""
        self.build_id = ""
        self.playbook_context = ""

    async def call(self, name: str, arguments: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
        if self.build_id:
            raw = await self._raw("build_tool_call", {"project_id": self.project_id, "build_id": self.build_id,
                                                    "name": name, "arguments": arguments or {}})
            dispatched = ToolDispatchResult.model_validate(raw)
            self._sync(dispatched.state)
            return dispatched.output
        if self.query_id:
            raw = await self._raw("evidence_tool_call", {"project_id": self.project_id, "query_id": self.query_id,
                                                       "name": name, "arguments": arguments or {}})
            dispatched = ToolDispatchResult.model_validate(raw)
            self._sync(dispatched.state)
            return dispatched.output
        if self.operation_id:
            raw = await self.control("agent_tool_call", {"name": name, "arguments": arguments or {}})
            dispatched = ToolDispatchResult.model_validate(raw)
            self._sync(dispatched.state)
            return dispatched.output
        self.state.authorize_tool(name)
        return await self._raw(name, arguments)

    async def _raw(self, name: str, arguments: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
        result = await self.session.call_tool(name, arguments or {})
        if result.isError:
            details = " ".join(item.text for item in result.content if item.type == "text")
            raise AgentError(f"Tool {name} failed: {details}")
        if result.structuredContent is not None:
            return JSON_OBJECT.validate_python(result.structuredContent)
        for item in result.content:
            if item.type == "text":
                try:
                    return JSON_OBJECT.validate_python(json.loads(item.text))
                except (ValueError, TypeError) as error:
                    raise AgentError(f"Tool {name} returned an invalid typed result.") from error
        raise AgentError(f"Tool {name} did not return structured data.")

    def _sync(self, state: AgentState) -> None:
        self.state.phase, self.state.budget = state.phase, state.budget
        self.state.brief_confirmed = state.brief_confirmed
        self.state.candidate_count, self.state.compiled_count = state.candidate_count, state.compiled_count
        self.state.evaluation, self.state.deployment_approved = state.evaluation, state.deployment_approved
        self.state.override_reason = state.override_reason

    async def start_run(self, project_id: str, brief: str, source_path: str, detector_model: str) -> None:
        raw = await self._raw("agent_run_begin", {"project_id": project_id, "brief": brief,
                                                "source_path": source_path, "detector_model": detector_model})
        begun = BeginOperationResult.model_validate(raw)
        if begun.conflict_error:
            raise AgentConflict(begun.conflict_error)
        operation = begun.operation
        if operation is None:
            raise AgentError("Agent operation start did not return an operation")
        self.project_id, self.operation_id = project_id, operation.id
        self._sync(operation.state)

    async def control(self, name: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        allowed = {"agent_record_decision", "agent_record_options", "agent_record_skills", "agent_plan_read", "agent_prepare_compile", "agent_capture_start",
                   "agent_capture_finish", "agent_tool_call", "agent_stage_plan", "agent_run_fail"}
        if name not in allowed or not self.operation_id:
            raise AgentError("Invalid durable agent control request")
        output = await self._raw(name, {**arguments, "project_id": self.project_id,
                                        "operation_id": self.operation_id})
        if isinstance(output.get("state"), dict):
            self._sync(AgentState.model_validate(output["state"]))
        return output

    async def capture_start(self, model: str, request: dict[str, JsonValue]) -> CapturedCall:
        if self.build_id:
            return CapturedCall.model_validate(await self._raw("build_capture_start", {
                "project_id": self.project_id, "build_id": self.build_id, "name": model, "request": request,
            }))
        if self.query_id:
            return CapturedCall.model_validate(await self._raw("evidence_capture_start", {
                "project_id": self.project_id, "query_id": self.query_id, "name": model, "request": request,
            }))
        raw = await self.control("agent_capture_start", {"kind": "llm", "name": model, "request": request})
        return CapturedCall.model_validate(raw)

    async def capture_finish(self, call_id: str, result: dict[str, JsonValue] | None, error: str | None = None) -> None:
        if self.build_id:
            self._sync(AgentState.model_validate(await self._raw("build_capture_finish", {
                "project_id": self.project_id, "build_id": self.build_id, "call_id": call_id, "result": result, "error": error,
            })))
            return
        if self.query_id:
            record = EvidenceOperation.model_validate(await self._raw("evidence_capture_finish", {
                "project_id": self.project_id, "query_id": self.query_id, "call_id": call_id, "result": result, "error": error,
            }))
            self._sync(record.operation.state)
            return
        raw = await self.control("agent_capture_finish", {"call_id": call_id, "result": result, "error": error})
        self._sync(AgentOperation.model_validate(raw).state)

    async def start_query(self, project_id: str, question: str) -> None:
        record = EvidenceOperation.model_validate(await self._raw("evidence_query_begin", {"project_id": project_id, "question": question}))
        self.project_id, self.query_id = project_id, record.operation.id
        self._sync(record.operation.state)

    async def bind_build(self, project_id: str, build_id: str) -> None:
        state = AgentState.model_validate(await self._raw("build_agent_state", {"project_id": project_id, "build_id": build_id}))
        self.project_id, self.build_id = project_id, build_id
        self._sync(state)

    async def record_refinement(self, decision: dict[str, JsonValue]) -> None:
        if not self.build_id:
            raise AgentError("A conversational refinement requires an active build")
        self._sync(AgentState.model_validate(await self._raw("build_record_refinement", {
            "project_id": self.project_id, "build_id": self.build_id, "decision": decision,
        })))

    async def record_build_skills(self, skills: list[SkillReference]) -> None:
        if not self.build_id:
            raise AgentError("Skill recording requires an active build")
        self._sync(AgentState.model_validate(await self._raw("build_record_skills", {
            "project_id": self.project_id, "build_id": self.build_id,
            "skills": [skill.model_dump(mode="json") for skill in skills],
        })))

    async def finish_query(self, *, decision: dict[str, JsonValue] | None = None,
                           answer: dict[str, JsonValue] | None = None, error: str | None = None) -> None:
        await self._raw("evidence_query_finish", {"project_id": self.project_id, "query_id": self.query_id,
                                                "decision": decision, "answer": answer, "error": error})


@asynccontextmanager
async def connect_tools(data_dir: str, state: AgentState) -> AsyncIterator[MCPTools]:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "mcp_server", "--data-dir", data_dir],
        env={key: os.environ[key] for key in (
            "VISION_APP_BINARY", "VISION_MODELS_DIR", "HF_HOME",
            "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTORCH_ENABLE_MPS_FALLBACK",
            "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "TZ",
        ) if key in os.environ},
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield MCPTools(session, state)
