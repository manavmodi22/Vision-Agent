"""Capture actual evidence tools and LLM calls without modifying build state."""

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue, TypeAdapter

from agent.evidence_state import EvidenceOperation
from agent.state_contracts import CapturedCall, ToolDispatchResult
from engine.evidence_audit import EvidenceAuditStore
from spec.evidence import EvidenceAnswer, EvidenceDecision

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def register_evidence_audit(server: FastMCP[None], store: EvidenceAuditStore) -> None:
    @server.tool()
    def evidence_query_begin(project_id: str, question: str) -> EvidenceOperation:
        """Create a read-only Q&A diagnostic operation, never a deployment or build operation."""
        return store.begin(project_id, question)

    @server.tool()
    def evidence_capture_start(project_id: str, query_id: str, name: str, request: dict[str, JsonValue]) -> CapturedCall:
        """Capture an actual local language-model attempt before the request."""
        return store.start_call(project_id, query_id, "llm", name, request)

    @server.tool()
    def evidence_capture_finish(project_id: str, query_id: str, call_id: str,
                                result: dict[str, JsonValue] | None, error: str | None = None) -> EvidenceOperation:
        """Complete only an LLM capture; tool results cannot be asserted by the agent."""
        if not any(call.id == call_id and call.kind == "llm" for call in store.get(project_id, query_id).operation.calls):
            raise ValueError("Only LLM captures may be finished through this tool")
        return store.finish_call(project_id, query_id, call_id, result, error)

    @server.tool()
    async def evidence_tool_call(project_id: str, query_id: str, name: str, arguments: dict[str, JsonValue]) -> ToolDispatchResult:
        """Dispatch one of two read-only evidence tools with authoritative budgets and traces."""
        call = store.start_call(project_id, query_id, "tool", name, arguments)
        try:
            raw: object = await server.call_tool(name, arguments)
            if isinstance(raw, tuple) and len(raw) == 2:
                raw = raw[1]
            output = JSON_OBJECT.validate_python(raw)
        except Exception as error:
            store.finish_call(project_id, query_id, call.id, None, str(error))
            raise
        record = store.finish_call(project_id, query_id, call.id, output)
        return ToolDispatchResult(output=output, state=record.operation.state)

    @server.tool()
    def evidence_query_finish(project_id: str, query_id: str, decision: EvidenceDecision | None = None,
                              answer: EvidenceAnswer | None = None, error: str | None = None) -> EvidenceOperation:
        """Save a captured answer or explicit failure in diagnostics only."""
        return store.finish(project_id, query_id, decision, answer, error)
