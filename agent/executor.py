"""Execute a persisted plan through MCP; planning and authority stay separate."""
from pydantic import JsonValue

from agent.contracts import PlanResult
from agent.machine import AgentError
from agent.mcp_client import MCPTools
from spec.platform import BuildPlan


async def execute_candidates(tools: MCPTools, proposed: PlanResult, source_path: str, detector_model: str) -> None:
    await tools.control("agent_prepare_compile", {"candidate_count": len(proposed.candidates)})
    plan = BuildPlan.model_validate(await tools.control("agent_plan_read", {}))
    if plan.candidates != proposed.candidates:
        raise AgentError("The saved plan differs from the planner proposal")
    for index, candidate in enumerate(plan.candidates):
        if candidate.inputs["source"].path != source_path:
            raise AgentError("The proposed source differs from the imported source")
        selected = next((item for item in plan.model_selections if item.candidate_index == index), None)
        if plan.planning_options_artifact_id and selected is None:
            raise AgentError("The saved plan has no model binding for this candidate")
        expected_model = selected.model_id if selected else detector_model
        if any(block.type in {"detect", "detect_open_vocab"} and block.params.get("model") != expected_model
               for block in candidate.blocks):
            raise AgentError("The proposed detector differs from its saved model selection")
        if selected and any(
            (block.type == "ocr" and block.params.get("model", "apple-vision") != selected.model_id)
            or (block.type == "barcode" and selected.model_id != "apple-vision")
            for block in candidate.blocks
        ):
            raise AgentError("The proposed reader differs from its saved model selection")
        arguments: dict[str, JsonValue] = {"project_id": tools.project_id, "spec": candidate.model_dump(mode="json", by_alias=True)}
        validation = await tools.call("pipeline_validate", arguments)
        if validation.get("valid") is not True:
            raise AgentError(f"The saved candidate did not compile: {validation.get('errors')}")
        preview = await tools.call("pipeline_run", arguments)
        if not preview.get("frames"):
            raise AgentError("The saved candidate produced no sample frames")
