"""Compile actual LLM decisions into authored, validated graph patterns."""

import re

from pydantic import JsonValue

from agent.contracts import PlanDecision, PlanResult
from agent.event_intent import event_intent
from agent.model_selection import selected_option, validate_model_choices
from agent.task_validation import (
    explicit_expected_text,
    unresolved_expected_text,
    validate_event_values,
    validate_reading_literal,
    validate_reading_mode,
)
from agent.templates import build_template
from spec.models import BlockSpec, PipelineSpec
from spec.planning import PlanningOptions


def require_complete_alert(decision: PlanDecision, brief: str) -> PlanDecision:
    """Ask only for missing conditions; supplied values must survive unchanged."""
    if not decision.choices:
        return decision
    detection = any(choice.pipeline_type == "detection" and choice.use_case != "labels" for choice in decision.choices)
    intent = event_intent(brief, parse_counts=detection)
    if intent.excludes_storage:
        validate_event_values(decision, brief)
    if not detection:
        return decision
    if intent.ambiguous_negation:
        validate_event_values(decision, brief)
    if intent.requested and not intent.disabled and (intent.unknown_full or intent.comparison is None):
        pallets = any(choice.use_case == "pallets" or "pallet" in choice.objects for choice in decision.choices)
        return PlanDecision(message="An event needs a confirmed count condition before the workflow can be proposed.",
            questions=["How many pallets make a lane full?" if pallets and intent.unknown_full else "At what object count should this app flag an event?"])
    validate_event_values(decision, brief)
    return decision


def plan_from_context(decision: PlanDecision, brief: str, source_path: str, detector_model: str,
                      context: dict[str, JsonValue] | None = None, options: PlanningOptions | None = None) -> PlanResult:
    """Enforce task prerequisites using the recorded model choice and engine facts."""
    decision = require_complete_alert(decision, brief)
    validate_reading_mode(decision, brief)
    latest = brief.rsplit("User request:\n", 1)[-1].replace("’", "'")
    comparisons = re.search(r"\b(check|verify|(?:mis)?match(?:es|ing)?|compare|comparison|expected|contains?|equals?)\b", latest, re.IGNORECASE)
    reading_only = re.search(r"\b(?:no|without)\s+(?:expected|comparison|matching)|\b(?:do not|don't)\s+(?:compare|match|check)", latest, re.IGNORECASE)
    if comparisons and not reading_only and any((choice.pipeline_type in {"ocr", "barcode"} or choice.use_case == "labels") and (not choice.expected_text or unresolved_expected_text(brief)) for choice in decision.choices):
        if explicit_expected_text(brief) is not None:
            raise ValueError("The expected comparison value is already supplied; the model must preserve it instead of asking for it again")
        return PlanResult(message="I need the expected value before adding the comparison.",
                          questions=["What text or barcode value should the app check against?"])
    validate_reading_literal(decision, brief)
    if context is not None and "zones_confirmed" in context:
        saved = context.get("saved_zone_ids", [])
        available = {name for name in saved if isinstance(name, str)} if isinstance(saved, list) else set()
        requested = [choice for choice in decision.choices if choice.use_zones or choice.use_case == "pallets"]
        missing = sorted({name for choice in requested for name in choice.zone_ids if name not in available})
        if requested and (not context.get("zones_confirmed") or not available or missing):
            names = missing or sorted({name for choice in requested for name in choice.zone_ids})
            description = ", ".join(names) if names else "the regions used by this task"
            return PlanResult(message="I need the actual region boundaries to build the requested spatial counts.",
                              questions=[f"Mark and save {description} on a representative image, then continue building."],
                              needs_zones=True)
    return compile_decision(decision, source_path, detector_model, options)


def compile_decision(decision: PlanDecision, source_path: str, detector_model: str,
                     options: PlanningOptions | None = None) -> PlanResult:
    if options is not None:
        validate_model_choices(decision, options)
    candidates: list[PipelineSpec] = []
    for index, choice in enumerate(decision.choices):
        reading = choice.pipeline_type in {"ocr", "barcode"}
        if options is None and choice.model_capability_id is not None:
            raise ValueError("A selected model requires its captured planning-options snapshot")
        model = selected_option(choice, options).model_id if options is not None else detector_model
        candidate = build_template("labels" if reading else choice.use_case, source_path, model, classes=choice.objects or None)[0]
        candidate.name = f"{choice.use_case}-candidate-{index + 1}"
        candidate.eval.metric = choice.metric
        candidate.eval.target = choice.target
        if choice.use_zones and choice.use_case != "pallets" and not reading:
            candidate.blocks.insert(2, BlockSpec.model_validate({"id": "zones", "type": "zone_filter",
                "params": {"zones": "zones/lanes.json", "include_ids": choice.zone_ids},
                "in": {"dets": "$det.dets"}}))
            next(block for block in candidate.blocks if block.type == "count_per_zone").inputs["dets"] = "$zones.dets"
        for block in candidate.blocks:
            if block.type == "ocr" and choice.pipeline_type == "barcode":
                block.type = "barcode"
            if block.type == "detect":
                block.params["min_conf"] = choice.min_confidence
                if choice.objects:
                    block.params["classes"] = list[JsonValue](choice.objects)
            if block.type == "rule":
                block.params["when"] = f"count {choice.count_operator} {choice.count_threshold if choice.count_threshold is not None else 1}"
                block.params["hold_s"] = choice.hold_seconds
            if block.type == "match":
                block.params["expected"] = choice.expected_text
                block.params["mode"] = choice.match_mode
                block.params["emit"] = choice.match_emit
            if block.type == "zone_filter" and choice.zone_ids:
                block.params["include_ids"] = list[JsonValue](choice.zone_ids)
        if not reading and choice.count_threshold is None:
            # A count-only task has no invented lane capacity or alert rule.
            candidate.blocks = [block for block in candidate.blocks if block.type not in {"rule", "sink_event"}]
        if reading and not choice.expected_text:
            candidate.blocks = [block for block in candidate.blocks if block.type not in {"match", "sink_event"}]
        candidates.append(PipelineSpec.model_validate(candidate.model_dump(mode="json", by_alias=True)))
    from agent.graph_summary import describe_candidates

    return PlanResult(
        message=describe_candidates(candidates) if candidates else "Clarification needed. " + decision.message,
        questions=decision.questions, candidates=candidates,
    )
