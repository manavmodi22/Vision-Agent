"""Durable operation, captured call and query contracts; no filesystem access."""

from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent.contracts import PlanDecision, PlanResult
from agent.machine import AgentState
from spec.planning import PlanningOptions
from spec.skills import SkillReference


class DurableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CapturedCall(DurableModel):
    id: str
    kind: Literal["tool", "llm"]
    name: str
    started_ns: int
    ended_ns: int | None = None
    status: Literal["running", "completed", "failed", "interrupted"] = "running"
    request: dict[str, JsonValue] = Field(default_factory=dict)
    result: dict[str, JsonValue] | None = None
    error: str | None = None


class StateChange(DurableModel):
    at: float = Field(default_factory=time)
    action: str
    phase: str
    detail: str = ""


class AgentOperation(DurableModel):
    id: str
    project_id: str
    trace_id: str
    root_span_id: str
    owner_pid: int
    created_at: float = Field(default_factory=time)
    updated_at: float = Field(default_factory=time)
    deadline: float
    status: Literal["running", "awaiting_commit", "completed", "failed", "interrupted", "invalidated"] = "running"
    input_fingerprint: str
    brief: str
    source_path: str
    detector_model: str
    state: AgentState
    calls: list[CapturedCall] = Field(default_factory=list)
    history: list[StateChange] = Field(default_factory=list)
    decision: PlanDecision | None = None
    result: PlanResult | None = None
    error: str | None = None
    skills: list[SkillReference] = Field(default_factory=list)
    planning_options: PlanningOptions | None = None


class ProjectAgentState(DurableModel):
    project_id: str
    revision: int = 0
    state: AgentState = Field(default_factory=AgentState)
    brief: str = ""
    clarification_count: int = Field(default=0, ge=0, le=3)
    active_operation_id: str | None = None
    last_operation_id: str | None = None
    history: list[StateChange] = Field(default_factory=list)


class BeginOperationResult(DurableModel):
    operation: AgentOperation | None = None
    conflict_error: str | None = None


class ToolDispatchResult(DurableModel):
    output: dict[str, JsonValue]
    state: AgentState


class TraceQuery(DurableModel):
    operation_id: str | None = None
    kind: Literal["tool", "llm", "run"] | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class TraceRecord(DurableModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    project_id: str
    operation_id: str
    kind: str
    start_ns: int
    end_ns: int
    status: str
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ReplayReport(DurableModel):
    operation_id: str
    original_status: str
    dry_run: Literal[True] = True
    effects_executed: Literal[False] = False
    reproduced: bool
    candidate_count: int
    captured_tool_calls: int
    captured_model_calls: int
    errors: list[str] = Field(default_factory=list)
    result: PlanResult | None = None
