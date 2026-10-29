"""Native API for durable progress, local traces and explicit dry-run replay."""

from typing import Literal

from fastapi import APIRouter, Query

from agent.evidence_state import EvidenceOperation, EvidenceReplay
from agent.state_contracts import (
    AgentOperation,
    ProjectAgentState,
    ReplayReport,
    TraceQuery,
    TraceRecord,
)
from engine.agent_state import AgentStateStore
from engine.evidence_audit import EvidenceAuditStore
from engine.service import WorkspaceService


def build_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter()
    store = AgentStateStore(service)
    evidence_audit = EvidenceAuditStore(service)

    @router.get("/projects/{project_id}/agent-state")
    def agent_state(project_id: str) -> ProjectAgentState:
        return store.get(project_id)

    @router.get("/projects/{project_id}/agent-runs")
    def agent_runs(project_id: str) -> list[AgentOperation]:
        return store.runs(project_id)

    @router.get("/projects/{project_id}/agent-runs/{operation_id}")
    def agent_run(project_id: str, operation_id: str) -> AgentOperation:
        store.get(project_id)
        return store.operation(project_id, operation_id)

    @router.get("/projects/{project_id}/traces")
    def traces(project_id: str, operation_id: str | None = None,
               kind: Literal["tool", "llm", "run"] | None = None,
               limit: int = Query(default=100, ge=1, le=1000)) -> list[TraceRecord]:
        service.get_project(project_id)
        return store.traces.query(project_id, TraceQuery(operation_id=operation_id, kind=kind, limit=limit))

    @router.post("/projects/{project_id}/agent-runs/{operation_id}/replay")
    def replay(project_id: str, operation_id: str) -> ReplayReport:
        return store.replay(project_id, operation_id)

    @router.get("/projects/{project_id}/evidence-queries/{query_id}")
    def evidence_query(project_id: str, query_id: str) -> EvidenceOperation:
        return evidence_audit.get(project_id, query_id)

    @router.post("/projects/{project_id}/evidence-queries/{query_id}/replay")
    def evidence_replay(project_id: str, query_id: str) -> EvidenceReplay:
        return evidence_audit.replay(project_id, query_id)

    return router
