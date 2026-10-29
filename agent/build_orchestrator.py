"""Agent-side describe-to-app actions. Every vision operation crosses MCP."""

from pydantic import JsonValue

from agent.machine import AgentState
from agent.mcp_client import MCPTools, connect_tools
from agent.planner import setting
from spec.build import BuildContext
from spec.models import EvalDataset, EvaluationResult, RunResult
from spec.refinement import RefinementBatch, RefinementPatch, RefinementResult


def select_candidate(results: list[EvaluationResult]) -> int:
    """Prefer passing candidates, then direction-aware margin versus declared target."""
    if not results:
        raise ValueError("No evaluated candidates are available")
    if len({(item.metric, item.target) for item in results}) != 1:
        raise ValueError("Candidates must use the same metric and target for a fair comparison")
    if len({item.dataset_hash for item in results}) != 1:
        raise ValueError("Candidates must use the same reviewed holdout dataset for comparison")

    def score(result: EvaluationResult) -> tuple[bool, float]:
        value = {"count_mae": result.count_mae, "precision": result.precision,
                 "recall": result.recall, "text_accuracy": result.text_accuracy}.get(result.metric)
        if value is None:
            raise ValueError("Candidate uses an unsupported evaluation metric")
        margin = result.target - value if result.metric == "count_mae" else value - result.target
        return result.passed, margin / max(abs(result.target), .01)

    return max(range(len(results)), key=lambda index: score(results[index]))


async def prepare_labels(settings: dict[str, JsonValue], build_id: str) -> tuple[BuildContext, EvalDataset | None]:
    project_id = setting(settings, "project_id")
    async with connect_tools(setting(settings, "mcp_data_dir"), AgentState()) as tools:
        await tools.bind_build(project_id, build_id)
        context = BuildContext.model_validate(await tools.call("build_prepare_review", {"project_id": project_id}))
        created = context.review_subset_created
        proposal = None
        if len(set(context.comparison_scopes)) > 1:
            return context, None
        if context.can_propose_labels and context.reviewed_count < context.image_count:
            proposal = EvalDataset.model_validate(await tools.call("build_propose_labels", {
                "project_id": project_id, "candidate_index": 0, "max_frames": 50,
            }))
            context = BuildContext.model_validate(await tools.call("build_context", {"project_id": project_id}))
            context.review_subset_created = created
        return context, proposal


async def refine_existing(settings: dict[str, JsonValue], build_id: str, patch: RefinementPatch | RefinementBatch, candidate_index: int) -> RefinementResult:
    project_id = setting(settings, "project_id")
    async with connect_tools(setting(settings, "mcp_data_dir"), AgentState()) as tools:
        await tools.bind_build(project_id, build_id)
        arguments: dict[str, JsonValue] = {"project_id": project_id, "build_id": build_id, "candidate_index": candidate_index}
        arguments["batch" if isinstance(patch, RefinementBatch) else "patch"] = patch.model_dump(mode="json")
        return RefinementResult.model_validate(await tools.call("build_refine", arguments))


async def _evaluate_all(tools: MCPTools, project_id: str) -> tuple[list[EvaluationResult], int, RunResult]:
    context = BuildContext.model_validate(await tools.call("build_context", {"project_id": project_id}))
    if len(context.comparison_scopes) != context.candidate_count or len(set(context.comparison_scopes)) > 1:
        raise ValueError("Candidates cover different object classes or zones. Align their detection scope before selecting a measured winner.")
    results = []
    for index in range(context.candidate_count):
        results.append(EvaluationResult.model_validate(await tools.call("eval_run", {
            "project_id": project_id, "candidate_index": index,
        })))
    selected = select_candidate(results)
    preview = RunResult.model_validate(await tools.call("pipeline_run", {"project_id": project_id, "candidate_index": selected}))
    return results, selected, preview


async def evaluate_all(settings: dict[str, JsonValue], build_id: str) -> tuple[list[EvaluationResult], int, RunResult]:
    project_id = setting(settings, "project_id")
    async with connect_tools(setting(settings, "mcp_data_dir"), AgentState()) as tools:
        await tools.bind_build(project_id, build_id)
        return await _evaluate_all(tools, project_id)


async def improve(settings: dict[str, JsonValue], build_id: str, candidate_index: int) -> tuple[list[EvaluationResult], int, RunResult]:
    project_id = setting(settings, "project_id")
    async with connect_tools(setting(settings, "mcp_data_dir"), AgentState()) as tools:
        await tools.bind_build(project_id, build_id)
        await tools.call("build_train", {"project_id": project_id, "build_id": build_id, "candidate_index": candidate_index})
        return await _evaluate_all(tools, project_id)


async def run_approved(settings: dict[str, JsonValue], build_id: str, candidate_index: int) -> RunResult:
    project_id = setting(settings, "project_id")
    async with connect_tools(setting(settings, "mcp_data_dir"), AgentState()) as tools:
        await tools.bind_build(project_id, build_id)
        return RunResult.model_validate(await tools.call("build_operate", {"project_id": project_id, "candidate_index": candidate_index}))
