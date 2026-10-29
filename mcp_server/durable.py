"""Durable state/control tools; none can commit, approve, alert or delete."""

from typing import Literal

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue, TypeAdapter

from agent.contracts import PlanDecision, PlanResult
from agent.state_contracts import (
    AgentOperation,
    BeginOperationResult,
    CapturedCall,
    ProjectAgentState,
    ToolDispatchResult,
)
from engine.agent_state import AgentConflict, AgentStateStore
from spec.platform import BuildPlan
from spec.skills import SkillReference

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def register_durable_tools(server: FastMCP[None], store: AgentStateStore) -> None:
    @server.tool()
    def agent_record_options(project_id: str, operation_id: str, snapshot_id: str) -> AgentOperation:
        """Bind interpretation to an exact, captured engine capability snapshot."""
        return store.record_options(project_id, operation_id, snapshot_id)

    @server.tool()
    def agent_record_skills(project_id: str, operation_id: str, skills: list[SkillReference]) -> AgentOperation:
        """Save exact installed playbook hashes; they cannot expand tool authority."""
        return store.record_skills(project_id, operation_id, skills)

    @server.tool()
    def agent_plan_read(project_id: str, operation_id: str) -> BuildPlan:
        """Read the immutable plan revision the executor must consume."""
        execution = store.platform.execution(project_id, operation_id)
        if execution is None:
            raise AgentConflict("No persisted plan is available for this execution")
        return store.platform.plan(project_id, execution.plan_id)

    @server.tool()
    def agent_state_get(project_id: str) -> ProjectAgentState:
        """Read reconciled project state; saved service evidence is authoritative."""
        return store.get(project_id)

    @server.tool()
    def agent_run_begin(project_id: str, brief: str, source_path: str, detector_model: str) -> BeginOperationResult:
        """Claim one bounded planning operation for an explicit user Build request."""
        try:
            return BeginOperationResult(operation=store.begin(project_id, brief, source_path, detector_model))
        except AgentConflict as error:
            return BeginOperationResult(conflict_error=str(error))

    @server.tool()
    def agent_record_decision(project_id: str, operation_id: str, decision: PlanDecision) -> AgentOperation:
        """Record a validated local-model decision before deterministic compilation."""
        return store.record_decision(project_id, operation_id, decision)

    @server.tool()
    def agent_prepare_compile(project_id: str, operation_id: str, candidate_count: int) -> AgentOperation:
        """Advance the explicit state machine to compile; does not validate a graph."""
        return store.prepare_compile(project_id, operation_id, candidate_count)

    @server.tool()
    def agent_capture_start(project_id: str, operation_id: str, kind: Literal["llm"],
                            name: str, request: dict[str, JsonValue]) -> CapturedCall:
        """Persist an LLM attempt before network execution so crashes are visible."""
        return store.start_call(project_id, operation_id, kind, name, request)

    @server.tool()
    def agent_capture_finish(project_id: str, operation_id: str, call_id: str,
                             result: dict[str, JsonValue] | None, error: str | None = None) -> AgentOperation:
        """Capture the actual LLM response or error and emit its local OTel span."""
        operation = store.operation(project_id, operation_id)
        if not any(call.id == call_id and call.kind == "llm" for call in operation.calls):
            raise AgentConflict("Only LLM calls may be completed through this capture endpoint")
        return store.finish_call(project_id, operation_id, call_id, result, error)

    @server.tool()
    async def agent_tool_call(project_id: str, operation_id: str, name: str,
                              arguments: dict[str, JsonValue]) -> ToolDispatchResult:
        """Dispatch a phase-allowed tool with durable budgets and captured results."""
        call = store.start_call(project_id, operation_id, "tool", name, arguments)
        try:
            raw: object = await server.call_tool(name, arguments)
            # FastMCP 1.x structured tools return (content, structured_content).
            if isinstance(raw, tuple) and len(raw) == 2:
                raw = raw[1]
            output = JSON_OBJECT.validate_python(raw)
        except Exception as error:
            store.finish_call(project_id, operation_id, call.id, None, str(error))
            raise
        operation = store.finish_call(project_id, operation_id, call.id, output)
        return ToolDispatchResult(output=output, state=operation.state)

    @server.tool()
    def agent_stage_plan(project_id: str, operation_id: str, result: PlanResult) -> AgentOperation:
        """Stage captured, previewed proposals for the originating UI request to commit."""
        return store.stage(project_id, operation_id, result)

    @server.tool()
    def agent_run_fail(project_id: str, operation_id: str, error: str) -> ProjectAgentState:
        """Record a planning failure; never promotes a phase or approves deployment."""
        store.fail(project_id, operation_id, error)
        return store.get(project_id)
