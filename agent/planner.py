"""Typed local-model planning with a real MCP client and enforced budgets."""

import asyncio
import json
from time import monotonic
from urllib.parse import urlsplit

import httpx
from openai import APIError, AsyncOpenAI, DefaultAsyncHttpxClient, Timeout
from pydantic import JsonValue
from pydantic_ai import Agent, ModelRetry, NativeOutput
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from agent.contracts import PlanDecision, PlanResult
from agent.decisions import plan_from_context
from agent.executor import execute_candidates
from agent.graph_structure import OUTPUTS
from agent.machine import AgentConflict, AgentError, AgentState
from agent.mcp_client import MCPTools, connect_tools
from agent.model_selection import planning_context, validate_model_choices
from agent.prompts.graph import GRAPH_PLANNER_V03, graph_syntax_example
from agent.recording import RecordedModel
from agent.skills import LoadedSkill, select_skills
from spec.authoring import GraphPlanDecision
from spec.planning import PlanningOptions


class PlannerError(ValueError):
    """Planning failed without substituting a template or another provider."""

    def __init__(self, message: str, *, tool_calls: int = 0, elapsed_s: float = 0) -> None:
        super().__init__(message)
        self.tool_calls = tool_calls
        self.elapsed_s = elapsed_s


MAX_INPUT_CHARS = 24000  # Includes guidance and output schema; not an exact token estimate.


def check_context_size(system: str, user: str, schema: object) -> None:
    if len(system) + len(user) + len(json.dumps(schema)) > MAX_INPUT_CHARS:
        raise PlannerError("The goal, project context and playbooks exceed the local context budget; shorten the request or project history")


def graph_playbooks(skills: tuple[LoadedSkill, ...]) -> str:
    """Keep complete guidance and identities; omit repeated catalog summaries."""
    return "\n\n".join(
        f"Playbook: {skill.reference.id}@{skill.reference.version}; sha256 {skill.reference.sha256}\n"
        f"{skill.body}" for skill in skills)


def local_model_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PlannerError("Model server URL must use HTTP(S) on localhost, 127.0.0.1 or ::1.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PlannerError("Model server URL cannot contain credentials, query parameters or fragments.")
    return value.rstrip("/")


def setting(settings: dict[str, JsonValue], name: str, default: str = "") -> str:
    value = settings.get(name, default)
    if not isinstance(value, str):
        raise PlannerError(f"Setting {name} must be a string.")
    return value


async def check_model(url: str, model: str) -> None:
    if not model.strip():
        raise PlannerError("Choose a planner model in Settings and load it in your local model server.")
    try:
        async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
            response = await client.get(f"{url}/models")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise PlannerError(f"Local model server is unavailable at {url}. Start it and load {model!r}.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise PlannerError("Local model server returned an invalid /models response.")
    models = [item.get("id") for item in payload["data"] if isinstance(item, dict)]
    if model not in models:
        raise PlannerError(f"Planner model {model!r} is not available. Load it or select a listed model in Settings.")


async def _generate(
    brief: str, source_path: str, settings: dict[str, JsonValue],
    tools: MCPTools, url: str, model_name: str,
) -> PlanResult:
    catalog = await tools.call("blocks_list")
    dataset_context = await tools.call("dataset_context", {"project_id": setting(settings, "project_id")})
    option_args: dict[str, JsonValue] = {"project_id": setting(settings, "project_id"), "operation_id": tools.operation_id}
    if setting(settings, "detector_model") == "fixture-color-v1":
        option_args["detection_constraint"] = "fixture-color-v1"
    options = PlanningOptions.model_validate(await tools.call("planning_options", option_args))
    await tools.control("agent_record_options", {"snapshot_id": options.snapshot_id})
    raw_blocks = catalog.get("blocks", [])
    supported_blocks: list[JsonValue] = []
    if isinstance(raw_blocks, list):
        for block in raw_blocks:
            if isinstance(block, dict):
                if block.get("type") in OUTPUTS:
                    # The visible prompt exposes flat authoring fields; retain actual
                    # catalog ports without repeating descriptions.
                    supported_blocks.append({key: value for key, value in block.items()
                                             if key in {"type", "inputs", "outputs"}})
    output_type = GraphPlanDecision
    output_schema = output_type.model_json_schema()
    context: dict[str, JsonValue] = {
        "source_path": source_path,
        "model_options": planning_context(options),
        "use_case": setting(settings, "use_case", "custom"),
        "dataset": dataset_context,
        "zones_path": "zones/lanes.json",
        "source_provenance": "synthetic fixture" if options.fixture_source else "imported media",
        "implemented_blocks": supported_blocks,
        "node_fields": {
            definition["properties"]["type"]["const"]: [
                name for name in definition["required"] if name not in {"id", "type"}
            ]
            for definition in output_schema["$defs"].values()
            if "id" in definition.get("properties", {})
            and "const" in definition.get("properties", {}).get("type", {})
        },
    }
    skills = select_skills(brief, setting(settings, "use_case", "custom"))
    await tools.control("agent_record_skills", {"skills": [skill.reference.model_dump(mode="json") for skill in skills]})
    question_count = settings.get("clarification_count", 0)
    if not isinstance(question_count, int) or not 0 <= question_count <= 3:
        raise PlannerError("Clarification count must be an integer between zero and three.")
    system_prompt = (GRAPH_PLANNER_V03 + graph_syntax_example(options) + "\n" + graph_playbooks(skills)
                     + f"\nYou may ask at most {3 - question_count} further questions in this project.")
    user_prompt = "Task brief:\n" + brief + "\nAuthoritative engine context:\n" + json.dumps(
        context, ensure_ascii=False, separators=(",", ":"))
    check_context_size(system_prompt, user_prompt, output_schema)
    # Slow local generation still shares the enclosing 180-second planning deadline.
    timeout = Timeout(read=150, connect=4, write=15, pool=4)
    async with AsyncOpenAI(base_url=url, api_key="local", max_retries=0, timeout=timeout,
                           http_client=DefaultAsyncHttpxClient(trust_env=False, timeout=timeout)) as client:
        model = OpenAIChatModel(
            model_name, provider=OpenAIProvider(openai_client=client),
            profile=OpenAIModelProfile(
                supports_json_schema_output=True,
                openai_supports_strict_tool_definition=False,
                openai_supports_tool_choice_required=False,
            ),
        )
        planner: Agent[None, GraphPlanDecision] = Agent(
            RecordedModel(model, tools, output_schema), output_type=NativeOutput(output_type, strict=True), retries=2,
            system_prompt=system_prompt,
            model_settings={"temperature": 0, "max_tokens": 2600},
            tool_timeout=15,
        )

        @planner.output_validator
        def validate_task(output: GraphPlanDecision) -> GraphPlanDecision:
            try:
                typed = PlanDecision.model_validate(output.model_dump(mode="json"))
                validate_model_choices(typed, options)
                plan_from_context(typed, brief, source_path, setting(settings, "detector_model", "owlv2-base-patch16"), dataset_context, options)
            except ValueError as error:
                raise ModelRetry(str(error)) from error
            return output

        response = await planner.run(
            user_prompt,
            usage_limits=UsageLimits(request_limit=5, tool_calls_limit=10, output_tokens_limit=12000),
        )
    tools.state.budget.check_time()
    raw_decision = PlanDecision.model_validate(response.output.model_dump(mode="json"))
    await tools.control("agent_record_decision", {"decision": raw_decision.model_dump(mode="json")})
    result = plan_from_context(raw_decision, brief, source_path, setting(settings, "detector_model", "owlv2-base-patch16"), dataset_context, options)
    if not result.needs_zones and len(result.questions) > 3 - question_count:
        raise PlannerError("The project's three-question budget is exhausted. Update the brief with the remaining task details.")
    return result


async def plan(brief: str, source_path: str, settings: dict[str, JsonValue]) -> PlanResult:
    """Propose and compile candidates. Evaluation and deployment are separate actions."""
    if not brief.strip() or len(brief) > 12000:
        raise PlannerError("Describe your task in 1–12,000 characters.")
    url = local_model_url(setting(settings, "model_url", "http://localhost:1234/v1"))
    model_name = setting(settings, "planner_model")
    data_dir = setting(settings, "mcp_data_dir")
    project_id = setting(settings, "project_id")
    if not data_dir or not project_id:
        raise PlannerError("The planner requires a saved project and its MCP workspace directory.")
    if not model_name.strip():
        raise PlannerError("Choose a planner model in Settings and load it in your local model server.")
    started = monotonic()
    state = AgentState()
    try:
        async with asyncio.timeout(state.budget.max_wall_seconds):
            async with connect_tools(data_dir, state) as tools:
                await tools.start_run(project_id, brief, source_path, setting(settings, "detector_model", "owlv2-base-patch16"))
                try:
                    await check_model(url, model_name)
                    result = await _generate(brief, source_path, settings, tools, url, model_name)
                    if result.candidates:
                        await execute_candidates(tools, result, source_path, setting(settings, "detector_model", "owlv2-base-patch16"))
                    result.tool_calls = state.budget.tool_calls
                    result.elapsed_s = monotonic() - started
                    result.operation_id = tools.operation_id
                    await tools.control("agent_stage_plan", {"result": result.model_dump(mode="json", by_alias=True)})
                    return result
                except Exception as error:
                    await tools.control("agent_run_fail", {"error": str(error)})
                    raise
    except AgentConflict:
        raise
    except TimeoutError as error:
        raise PlannerError("Planning reached its wall-clock budget. Shorten the brief or use a smaller local model.",
                           tool_calls=state.budget.tool_calls, elapsed_s=monotonic() - started) from error
    except (APIError, httpx.HTTPError, UnexpectedModelBehavior, UsageLimitExceeded, AgentError) as error:
        raise PlannerError(f"Local planning failed: {error}", tool_calls=state.budget.tool_calls,
                           elapsed_s=monotonic() - started) from error
    except ExceptionGroup as error:
        cause: BaseException = error
        while isinstance(cause, BaseExceptionGroup) and cause.exceptions:
            cause = cause.exceptions[0]
        if isinstance(cause, AgentConflict):
            raise cause from error
        raise PlannerError(f"Local planning failed: {cause}", tool_calls=state.budget.tool_calls,
                           elapsed_s=monotonic() - started) from error
