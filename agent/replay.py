"""Effect-free reconstruction: captured decisions/results only, no tool clients."""

from agent.contracts import PlanResult
from agent.decisions import plan_from_context
from agent.state_contracts import AgentOperation, ReplayReport


def replay_operation(operation: AgentOperation) -> ReplayReport:
    errors: list[str] = []
    rebuilt: PlanResult | None = None
    if operation.decision is None:
        errors.append("No validated model decision was captured; there is no plan to reconstruct.")
    else:
        context = next((call.result for call in operation.calls if call.name == "dataset_context" and call.status == "completed"), None)
        rebuilt = plan_from_context(operation.decision, operation.brief, operation.source_path, operation.detector_model,
                                    context, operation.planning_options)
        rebuilt.operation_id = operation.id
        rebuilt.tool_calls = operation.state.budget.tool_calls
        if operation.result:
            rebuilt.elapsed_s = operation.result.elapsed_s
        for candidate in rebuilt.candidates:
            payload = candidate.model_dump(mode="json", by_alias=True)
            valid = any(call.name == "pipeline_validate" and call.request.get("spec") == payload
                        and call.status == "completed" and call.result and call.result.get("valid") is True
                        for call in operation.calls)
            previewed = any(call.name == "pipeline_run" and call.request.get("spec") == payload
                            and call.status == "completed" and call.result and call.result.get("frames")
                            for call in operation.calls)
            if not valid or not previewed:
                errors.append(f"Candidate {candidate.name} lacks captured successful validation and preview.")
        if operation.result is None:
            errors.append("Original operation did not stage a complete result.")
        elif rebuilt != operation.result:
            errors.append("Reconstructed result differs from the captured original result.")
    if operation.status in {"failed", "interrupted", "invalidated"}:
        errors.append(f"Original operation ended as {operation.status}: {operation.error or 'no details'}")
    return ReplayReport(
        operation_id=operation.id, original_status=operation.status,
        reproduced=not errors, candidate_count=len(rebuilt.candidates) if rebuilt else 0,
        captured_tool_calls=sum(call.kind == "tool" for call in operation.calls),
        captured_model_calls=sum(call.kind == "llm" for call in operation.calls),
        errors=errors, result=rebuilt,
    )
