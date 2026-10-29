"""Interpret local conversational edits without replacing the current graph."""
from __future__ import annotations

import asyncio
import json
import re
from time import monotonic

import httpx
from openai import APIError, AsyncOpenAI, DefaultAsyncHttpxClient
from pydantic import JsonValue
from pydantic_ai import Agent, ModelRetry, NativeOutput
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from agent.machine import AgentError, AgentState
from agent.mcp_client import MCPTools, connect_tools
from agent.planner import (
    MAX_INPUT_CHARS,
    PlannerError,
    check_context_size,
    check_model,
    local_model_url,
    setting,
)
from agent.recording import RecordedModel
from agent.refinement_capabilities import delivery_question
from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
from agent.refinement_output import RefinementModelDecision
from agent.skills import render_skills, select_skills
from spec.models import PipelineSpec
from spec.refinement import RefinementContext, RefinementPatch

REFINEMENT_PROMPT = """You edit an existing visual application, using only the supplied typed patches.
Read the actual graph, existing values, current goal and conversation. The last user request changes this app.
An answer to your question completes the previous request; interpret them together.
Return JSON {message, questions, patches}. Clear requests: questions=[] and one or more patches.
Ambiguous requests: patches=[] and at most three short essential questions. Never guess a business threshold.
Never regenerate a graph, remove unrelated blocks, approve labels/deployment/training, execute code, or invent results.
Do not ask technical questions when values or sensible semantics are already explicit. No unnecessary confirmation.

Supported patch kinds and fields:
confidence: confidence fraction0..1 (70%=0.7). 'Only show detections at least70percent sure' means confidence0.7.
add_classes: classes added to current labels. Map obvious plurals to exact existing names. Preserve prior classes.
remove_classes: classes exact existing labels explicitly removed. replace_classes: explicit replacement label list.
For replacing pallets with forklifts, use {"kind":"replace_classes","classes":["forklift"]}; classes are the NEW complete detector labels.
Class changes leave the current evaluation metric and target unchanged. Do not add an eval_target patch or ask about evaluation unless requested.
count_rule: count_threshold number, count_operator >= <= == != > <, hold_s seconds; supply only requested fields.
'At least four objects for half a minute' means count_threshold4,count_operator>=,hold_s30.
Counts aggregate every detector class in that branch. A class-specific rule with a mixed-class detector needs clarification
about filtering that branch; do not silently claim class-specific counting or remove classes to achieve it.
expected_text: expected_text literal required label value, match_mode exact|contains if requested.
sample_fps: fps>0..60. Resolve relative requests against current frame_sample.fps (half of2=1).
eval_target: eval_target and optional eval_metric count_mae|precision|recall|text_accuracy. Preserve current metric unless asked.
crop: crop_box [x0,y0,x1,y1] normalized to the transform input. Preserve supplied bounds exactly.
Left/right/top/bottom half means [0,0,0.5,1]/[0.5,0,1,1]/[0,0,1,0.5]/[0,0.5,1,1].
resize: width and height integer pixels1..8192; both must come from the user (e.g.640x480). Do not guess dimensions.
For crop/resize, block_id names the intended existing detector/reader or transform. Without it there must be one image consumer.
The unique existing transform in that consumer's image path is updated, or a transform is inserted before the consumer.
Shared preprocessing is copied for the selected branch; other readers and model choices remain unchanged.
If multiple crops/resizes already exist on that path, ask which transform. Bounds are relative to its input; do not invent full-frame coordinates for an already-cropped input.
Accuracy/recall/precision/text targets are fractions0..1; count_mae is a nonnegative absolute count error.
Only fields relevant to each kind are allowed. Never add null unrelated fields. Multiple edits form one patches list.
Use block_id only to disambiguate an actual matching existing block. If several blocks could be meant, ask which one.
count_rule can add rule+sink after the unique existing count_per_zone if absent; a new rule needs a threshold.
expected_text can add a comparison after unique OCR/barcode if absent; it preserves existing event connections and never adds a sink.
Only crop/resize can add preprocessing. New models, reader branches and other block types require a new structural build request.
Confidence defaults to the selected candidate. All other goal edits default to all alternatives. Omit scope unless explicitly requested.
Preserve prior classes for additive requests. Only remove or replace when explicitly requested. Do not invent synonyms for saved names.
Do not drop part of a compound request. If any part is unsupported or ambiguous, ask rather than partially editing.
For 'make it more accurate' without a measurable requested change, ask which errors or target matter; do not guess a confidence direction.
Interpret the LAST USER REQUEST below. The field descriptions above are a vocabulary, not tasks to execute.
Count/alert/event thresholds concern count_rule; detection certainty concerns confidence. They are different settings.
For a clear count+duration request, emit count_rule with its count_threshold, count_operator and hold_s, without asking again.
"""


def _model_context(context: RefinementContext, prompt: str, limit: int = 17000) -> str:
    value = context.model_dump(mode="json", by_alias=True)
    history = context.conversation[-6:]
    value["conversation"] = history
    value["history_abbreviated"] = len(history) < len(context.conversation)
    encoded = json.dumps(value, separators=(",", ":"))
    while len(encoded) + len(prompt) > limit and len(history) > 2:
        history.pop(0)
        value["history_abbreviated"] = True
        encoded = json.dumps(value, separators=(",", ":"))
    if len(encoded) + len(prompt) > limit:
        raise PlannerError("The current app and follow-up exceed the local context budget; shorten the request")
    return encoded


async def _interpret_local(prompt: str, context: RefinementContext, tools: MCPTools,
                           url: str, model_name: str) -> RefinementDecision:
    remaining = max(0, 3 - context.clarification_count)
    system_prompt = REFINEMENT_PROMPT + "\n" + tools.playbook_context + f"\nYou may ask at most {remaining} further questions."
    schema = RefinementModelDecision.model_json_schema()
    encoded = _model_context(context, prompt, MAX_INPUT_CHARS - len(system_prompt) - len(json.dumps(schema)) - 100)
    user_prompt = "Authoritative current app:\n" + encoded + "\nUser request:\n" + prompt
    check_context_size(system_prompt, user_prompt, schema)
    async with AsyncOpenAI(base_url=url, api_key="local", max_retries=0, timeout=60,
                           http_client=DefaultAsyncHttpxClient(trust_env=False, timeout=60)) as client:
        model = OpenAIChatModel(model_name, provider=OpenAIProvider(openai_client=client),
            profile=OpenAIModelProfile(supports_json_schema_output=True,
                openai_supports_strict_tool_definition=False, openai_supports_tool_choice_required=False))
        planner: Agent[None, RefinementModelDecision] = Agent(
            RecordedModel(model, tools, RefinementModelDecision.model_json_schema()),
            output_type=NativeOutput(RefinementModelDecision, strict=True), retries=2,
            system_prompt=system_prompt,
            model_settings={"temperature": 0, "max_tokens": 1600})

        @planner.output_validator
        def validate(output: RefinementModelDecision) -> RefinementModelDecision:
            if len(output.questions) > remaining:
                raise PlannerError("The three-question budget is exhausted; provide the remaining specifics in a new request")
            try:
                validate_refinement_intent(output.normalized(), prompt, context)
            except ValueError as error:
                raise ModelRetry(f"{error}. Correct the typed patch or ask an essential question with patches=[]") from error
            return output

        response = await planner.run(user_prompt,
            usage_limits=UsageLimits(request_limit=3, output_tokens_limit=5000))
    return response.output.normalized()


async def interpret_refinement(prompt: str, settings: dict[str, JsonValue], build_id: str,
                               candidate_index: int = 0) -> RefinementDecision:
    """Preflight known capabilities, then interpret edits with the local model."""
    if not prompt.strip() or len(prompt) > 10000:
        raise PlannerError("Describe the change in 1–10,000 characters")
    project_id, data_dir = setting(settings, "project_id"), setting(settings, "mcp_data_dir")
    if not project_id or not data_dir:
        raise PlannerError("Refinement needs a saved project and active build")
    url, model_name = local_model_url(setting(settings, "model_url", "http://localhost:1234/v1")), setting(settings, "planner_model")
    started, state = monotonic(), AgentState()
    try:
        async with asyncio.timeout(90):
            async with connect_tools(data_dir, state) as tools:
                await tools.bind_build(project_id, build_id)
                context = RefinementContext.model_validate(await tools.call("build_refinement_context", {
                    "project_id": project_id, "candidate_index": candidate_index}))
                previous_question = context.conversation[-1].get("content", "") if context.conversation else ""
                if question := delivery_question(prompt, previous_question):
                    if context.clarification_count >= 3:
                        raise PlannerError("The three-question budget is exhausted. Configure delivery in Alerts and start a vision-only request.")
                    decision = RefinementDecision(source="capability_guard", message=question, questions=[question], patches=[])
                    await tools.record_refinement(decision.model_dump(mode="json"))
                    return decision
                await check_model(url, model_name)
                skills = select_skills(prompt, setting(settings, "use_case", "custom"))
                tools.playbook_context = render_skills(skills)
                await tools.record_build_skills([skill.reference for skill in skills])
                decision = await _interpret_local(prompt, context, tools, url, model_name)
                await tools.record_refinement(decision.model_dump(mode="json"))
                return decision
    except TimeoutError as error:
        raise PlannerError("Refinement reached its 90-second deadline; the current app is unchanged",
                           tool_calls=state.budget.tool_calls, elapsed_s=monotonic() - started) from error
    except (APIError, httpx.HTTPError, UnexpectedModelBehavior, UsageLimitExceeded, AgentError) as error:
        raise PlannerError(f"Local refinement failed: {error}", tool_calls=state.budget.tool_calls,
                           elapsed_s=monotonic() - started) from error
    except ExceptionGroup as error:
        cause: BaseException = error
        while isinstance(cause, BaseExceptionGroup) and cause.exceptions:
            cause = cause.exceptions[0]
        raise PlannerError(f"Local refinement failed: {cause}", tool_calls=state.budget.tool_calls,
                           elapsed_s=monotonic() - started) from error

_CONFIDENCE = re.compile(
    r"(?:please\s+)?(?:(?:raise|lower|set|change|increase|decrease|update)\s+)?"
    r"(?:the\s+)?(?:detector\s+)?confidence(?:\s+threshold)?\s*(?:to|=|:)?\s*"
    r"(\d+(?:\.\d+)?|\.\d+)\s*(%)?\s*[.!]?", re.IGNORECASE)
_ADD_CLASSES = re.compile(r"(?:please\s+)?(?:also\s+(?:count|detect|include)|add(?:\s+class(?:es)?)?|include)\s+(.+?)[.!]?", re.IGNORECASE)
_ALIASES = {"people": "person", "persons": "person", "forklifts": "forklift", "pallets": "pallet",
            "cartons": "carton", "boxes": "box"}


def parse_refinement(prompt: str, candidates: list[PipelineSpec]) -> RefinementPatch | None:
    if not candidates:
        return None
    text = prompt.strip()
    confidence = _CONFIDENCE.fullmatch(text)
    if confidence:
        value = float(confidence.group(1)) / (100 if confidence.group(2) else 1)
        return RefinementPatch(kind="confidence", confidence=value)
    added = _ADD_CLASSES.fullmatch(text)
    if added is None:
        return None
    # Spatial/conditional edits need their own interpretation; never swallow them
    # into a class label and accidentally claim that the condition was implemented.
    if re.search(r"\b(in|near|when|if|per|inside|outside|where|show|alert|threshold|confidence)\b", added.group(1), re.IGNORECASE):
        return None
    existing: dict[str, str] = {}
    for candidate in candidates:
        for block in candidate.blocks:
            labels = block.params.get("classes")
            if block.type in {"detect", "detect_open_vocab"} and isinstance(labels, list):
                existing.update({label.casefold(): label for label in labels if isinstance(label, str)})
    names = []
    for part in re.split(r"\s*,\s*|\s+and\s+", added.group(1), flags=re.IGNORECASE):
        name = part.strip().strip("\"'")
        if not name or len(name.split()) > 5:
            return None
        canonical = existing.get(name.casefold(), _ALIASES.get(name.casefold(), name.casefold()))
        canonical = existing.get(canonical.casefold(), canonical)
        if canonical not in existing.values() and canonical not in _ALIASES.values():
            # Arbitrary vocabulary remains supported by typed local interpretation;
            # the legacy fast path handles only these exact familiar class names.
            return None
        if canonical not in names:
            names.append(canonical)
    return RefinementPatch(kind="add_classes", classes=names)
