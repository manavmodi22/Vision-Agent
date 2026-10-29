"""Composition boundary: read-only agent Q&A diagnostics and local OTel spans."""

import os
import re
import uuid
from time import time, time_ns
from typing import Literal

from pydantic import JsonValue

from agent.evidence_state import EvidenceOperation, EvidenceReplay
from agent.machine import AgentBudget, AgentState, Phase
from agent.state_contracts import AgentOperation, CapturedCall
from engine.agent_traces import AgentTraceStore
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.evidence import EvidenceAnswer, EvidenceDecision


class EvidenceAuditStore:
    """Writes only diagnostic records, never annotations, candidates or approval."""

    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.traces = AgentTraceStore(service.repository.root)

    def save(self, record: EvidenceOperation) -> None:
        operation = record.operation
        operation.updated_at = time()
        atomic_model(self.service.root(operation.project_id) / "evidence-queries" / f"{operation.id}.json", record)

    def get(self, project_id: str, query_id: str) -> EvidenceOperation:
        with self.service.repository.lock:
            return self._get(project_id, query_id)

    def _get(self, project_id: str, query_id: str) -> EvidenceOperation:
        if not re.fullmatch(r"[0-9a-f]{32}", query_id):
            raise ValueError("Invalid evidence query identifier")
        path = self.service.root(project_id) / "evidence-queries" / f"{query_id}.json"
        if not path.exists():
            raise FileNotFoundError("Evidence query record not found")
        record = EvidenceOperation.model_validate_json(path.read_text())
        operation = record.operation
        alive = True
        try:
            os.kill(operation.owner_pid, 0)
        except ProcessLookupError:
            alive = False
        if operation.status == "running" and (not alive or time() > operation.deadline):
            operation.status, operation.error = "interrupted", "Query process ended or its 60-second deadline expired"
            for call in operation.calls:
                if call.status == "running":
                    call.status, call.error, call.ended_ns = "interrupted", operation.error, time_ns()
                    self.traces.emit(operation, call)
            self.save(record)
            self.traces.emit(operation)
        return record

    def begin(self, project_id: str, question: str) -> EvidenceOperation:
        if not question.strip() or len(question) > 2000:
            raise ValueError("Evidence question must contain 1–2000 characters")
        self.service.get_project(project_id)
        record = EvidenceOperation(operation=AgentOperation(
            id=uuid.uuid4().hex, project_id=project_id, trace_id=uuid.uuid4().hex, root_span_id=uuid.uuid4().hex[:16],
            owner_pid=os.getpid(), deadline=time() + 60, input_fingerprint="read-only-evidence-snapshot",
            brief=question, source_path="", detector_model="",
            state=AgentState(phase=Phase.QUERY, budget=AgentBudget(max_tool_calls=2, max_model_calls=2, max_wall_seconds=60)),
        ))
        self.save(record)
        return record

    def start_call(self, project_id: str, query_id: str, kind: Literal["llm", "tool"],
                   name: str, request: dict[str, JsonValue]) -> CapturedCall:
        with self.service.repository.lock:
            record = self.get(project_id, query_id)
            operation = record.operation
            if operation.status != "running" or operation.owner_pid != os.getpid():
                raise ValueError("Evidence query is no longer active in this MCP session")
            if kind == "tool":
                operation.state.authorize_tool(name)
                if request.get("project_id") != project_id:
                    raise ValueError("Evidence query tools are bound to their originating project")
            else:
                operation.state.budget.consume_model()
            call = CapturedCall(id=uuid.uuid4().hex, kind=kind, name=name, request=request, started_ns=time_ns())
            operation.calls.append(call)
            self.save(record)
            return call

    def finish_call(self, project_id: str, query_id: str, call_id: str,
                    result: dict[str, JsonValue] | None, error: str | None = None) -> EvidenceOperation:
        with self.service.repository.lock:
            record = self.get(project_id, query_id)
            call = next((item for item in record.operation.calls if item.id == call_id), None)
            if call is None or call.status != "running":
                raise ValueError("Evidence capture is not an active call")
            call.result, call.error, call.ended_ns = result, error, time_ns()
            call.status = "failed" if error else "completed"
            self.save(record)
            self.traces.emit(record.operation, call)
            return record

    def finish(self, project_id: str, query_id: str, decision: EvidenceDecision | None,
               answer: EvidenceAnswer | None, error: str | None = None) -> EvidenceOperation:
        with self.service.repository.lock:
            record = self.get(project_id, query_id)
            if record.operation.status != "running":
                raise ValueError("Evidence query is already finished")
            if not error:
                if decision is None or answer is None:
                    raise ValueError("A successful query requires its typed interpretation and answer")
                if decision.query is not None:
                    executed = [call for call in record.operation.calls
                                if call.name == "evidence_execute" and call.status == "completed"]
                    expected = answer.model_copy(update={"query_id": None}).model_dump(mode="json")
                    if not executed or executed[-1].result != expected:
                        raise ValueError("The answer differs from the captured deterministic execution")
            record.decision, record.answer = decision, answer
            record.operation.status = "failed" if error else "completed"
            record.operation.error = error
            for call in record.operation.calls:
                if call.status == "running":
                    call.status, call.error, call.ended_ns = "interrupted", error or "Query ended", time_ns()
                    self.traces.emit(record.operation, call)
            self.save(record)
            self.traces.emit(record.operation)
            return record

    def replay(self, project_id: str, query_id: str) -> EvidenceReplay:
        record = self.get(project_id, query_id)
        errors: list[str] = []
        if record.operation.status != "completed" or record.decision is None or record.answer is None:
            errors.append("The query did not complete with a captured answer")
        elif record.decision.query is not None:
            calls = [call for call in record.operation.calls if call.name == "evidence_execute" and call.status == "completed"]
            if not calls or calls[-1].request.get("query") != record.decision.query.model_dump(mode="json"):
                errors.append("The captured execution does not match the recorded typed query")
            elif calls[-1].result != record.answer.model_copy(update={"query_id": None}).model_dump(mode="json"):
                errors.append("The saved answer differs from the captured tool result")
        return EvidenceReplay(query_id=query_id, reproduced=not errors, errors=errors, answer=record.answer)
