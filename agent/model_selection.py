"""Pure selection checks over the engine's captured capability options."""
from collections import Counter

from pydantic import JsonValue

from agent.contracts import PatternChoice, PlanDecision
from spec.planning import CandidateModelSelection, PlanningModelOption, PlanningOptions

MAX_EXPERIMENTAL_PROMPT_MODELS = 8


def planning_context(options: PlanningOptions) -> dict[str, JsonValue]:
    """Compact facts for the prompt; the complete typed receipt remains captured."""
    def compact(option: PlanningModelOption) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = option.model_dump(mode="json", exclude_none=True, include={
            "capability_id", "task_types", "vocabulary", "supported_classes", "synthetic", "readiness", "selection_basis"})
        if option.training_provenance:
            value["training_provenance"] = option.training_provenance.model_dump(mode="json", exclude_none=True,
                include={"origin", "initialization", "training_state", "use_scope", "base_model_id",
                         "training_samples", "optimizer_steps", "preserved_classes", "evaluation_status"})
        if option.selection_basis in {"requires_explicit_request", "explicit_experiment"}:
            value["selection_reason"] = option.selection_reason
        return value

    experimental = {option.capability_id for option in options.experimental_models}
    shown = options.experimental_models[:MAX_EXPERIMENTAL_PROMPT_MODELS]
    purposes = Counter(option.training_provenance.use_scope if option.training_provenance else "unknown"
                       for option in options.experimental_models)
    purpose_counts: dict[str, JsonValue] = {purpose:count for purpose, count in purposes.items()}
    return {"snapshot_id":options.snapshot_id,
        "eligible_models":[compact(option) for option in options.eligible_models],
        "experimental_models":[{"capability_id":option.capability_id,
            "purpose":option.training_provenance.use_scope if option.training_provenance else "unknown",
            "reason":option.selection_reason} for option in shown],
        "experimental_summary":{"total_count":len(options.experimental_models), "shown_count":len(shown),
            "omitted_count":len(options.experimental_models) - len(shown), "purpose_counts":purpose_counts},
        "blocked_options":[{"capability_id":option.capability_id, "reason":option.reason[:180]}
                           for option in options.blocked_options if option.capability_id not in experimental],
        "evidence_limits":"Prerequisites permit bounded validation. Training facts are recorded provenance, not measured quality. No scored reports are attached; a dataset hash is not a score. Scene independence is not established."}


def requested_classes(choice: PatternChoice) -> list[str]:
    if choice.objects:
        return choice.objects
    return ["damaged carton", "damaged pallet"] if choice.use_case == "damage" else ["pallet"]


def selected_option(choice: PatternChoice, options: PlanningOptions) -> PlanningModelOption:
    identifier = choice.model_capability_id
    if not identifier or not choice.model_reason or not choice.model_reason.strip():
        raise ValueError("Every new candidate must name an eligible model capability and a proposed reason")
    option = next((item for item in options.eligible_models if item.capability_id == identifier), None)
    if option is None:
        blocked = next((item.reason for item in options.blocked_options if item.capability_id == identifier), "Unknown or unsupported model capability")
        raise ValueError(f"Cannot select {identifier}: {blocked}. Choose an eligible option or ask about the blocker; do not substitute silently")
    if options.schema_version == "0.2":
        if option.selection_basis not in {"default", "explicit_experiment"}:
            raise ValueError("This model is not authorized for the current selection mode")
        if option.selection_basis == "explicit_experiment" and (option.model_id not in options.explicit_model_ids or not options.request_hash):
            raise ValueError("An experimental model requires authorization captured from the originating user request")
    task = "ocr" if choice.use_case == "labels" and choice.pipeline_type == "detection" else choice.pipeline_type
    if task not in option.task_types:
        raise ValueError(f"{identifier} does not implement task {task}")
    if option.synthetic and not options.fixture_source:
        raise ValueError("Synthetic fixture adapters cannot be selected for real project media")
    if task == "detection" and option.vocabulary == "closed":
        missing = set(requested_classes(choice)) - set(option.supported_classes)
        if missing:
            raise ValueError(f"{identifier} does not cover the requested classes: {', '.join(sorted(missing))}. Preserve the user's classes and choose a compatible model or ask")
    return option


def validate_model_choices(decision: PlanDecision, options: PlanningOptions) -> list[CandidateModelSelection]:
    if len(decision.choices) > 1:
        objectives = {(choice.pipeline_type, choice.metric, choice.target, tuple(sorted(requested_classes(choice))),
                       choice.use_zones, tuple(sorted(choice.zone_ids)), choice.count_threshold, choice.count_operator,
                       choice.hold_seconds, choice.expected_text, choice.match_mode, choice.match_emit)
                      for choice in decision.choices}
        if len(objectives) != 1:
            raise ValueError("Model alternatives must implement the same task, classes, regions, behavior, metric and target")
    selections = []
    for index, choice in enumerate(decision.choices):
        option = selected_option(choice, options)
        selections.append(CandidateModelSelection(candidate_index=index, capability_id=option.capability_id,
            model_id=option.model_id, adapter_id=option.adapter_id, proposed_reason=choice.model_reason or "",
            options_snapshot_id=options.snapshot_id))
    return selections
