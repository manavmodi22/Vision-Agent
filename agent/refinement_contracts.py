"""Interpretation guards independent of engine mutation or inference."""

import re
from typing import Literal

from pydantic import Field, model_validator

from agent.contracts import PatternChoice, PlanDecision
from agent.event_intent import event_intent
from agent.refinement_capabilities import delivery_question
from agent.refinement_fidelity import validate_explicit_fidelity
from agent.task_validation import reading_instruction_text, validate_reading_mode
from spec.models import Contract
from spec.preprocessing import preprocessing_target
from spec.refinement import RefinementContext, RefinementPatch


class RefinementDecision(Contract):
    source: Literal["local_model", "capability_guard"] = "local_model"
    message: str = Field(min_length=1, max_length=1000)
    questions: list[str] = Field(max_length=3)
    patches: list[RefinementPatch] = Field(max_length=8)

    @model_validator(mode="after")
    def one_outcome(self) -> "RefinementDecision":
        if bool(self.questions) == bool(self.patches):
            raise ValueError("Return either essential questions or typed patches, never both or neither")
        if any(not question.strip() or len(question) > 500 for question in self.questions):
            raise ValueError("Questions must be nonempty and at most 500 characters")
        if self.source == "capability_guard" and self.patches:
            raise ValueError("Capability checks can only ask a question, never emit edits")
        return self


def validate_refinement_intent(decision: RefinementDecision, prompt: str, context: RefinementContext) -> None:
    """Reject unsupported target assumptions; model text cannot confer authority."""
    if decision.questions:
        return
    previous_question = context.conversation[-1].get("content", "") if context.conversation else ""
    if question := delivery_question(prompt, previous_question):
        raise ValueError(question)
    validate_explicit_fidelity(decision.patches, prompt, context)
    validate_comparison_event_topology(decision, prompt, context)
    for patch in decision.patches:
        numeric = any(getattr(patch, name) is not None for name in (
            "confidence", "count_threshold", "hold_s", "fps", "eval_target"))
        if numeric and not re.search(
            r"\d|\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|dozen|half|quarter|double|twice|triple)\b", prompt, re.I
        ):
            raise ValueError("The user supplied no numeric value or explicit relative factor; ask instead of inventing a threshold")
        if patch.kind == "confidence" and not re.search(
            r"\b(confidence|confident|sure|certainty|detection threshold|detector threshold|score)\b", prompt, re.I
        ):
            raise ValueError("The request does not identify detector confidence; do not substitute it for a count or alert threshold")
        if patch.kind in {"remove_classes", "replace_classes"} and not re.search(
            r"\b(remove|drop|exclude|ignore|stop|instead|replace|only|no longer|rather than|don't|do not)\b", prompt, re.I
        ):
            raise ValueError("Class removal or replacement requires an explicit user request; otherwise ask")
        if patch.kind != "confidence" and patch.scope == "selected" and not re.search(
            r"\b(selected|this candidate|candidate\s*\d+|alternative\s*\d+|only this|current candidate)\b", prompt, re.I
        ):
            raise ValueError("Goal changes apply to all alternatives unless the user explicitly selects one")
        requested_indices = [int(number) - 1 for number in re.findall(r"\b(?:candidate|alternative)\s+(\d+)\b", prompt, re.I)]
        if patch.target_scope() == "selected" and any(index != context.selected_candidate_index for index in requested_indices):
            raise ValueError("The requested candidate is not the current selected candidate; ask which active selection the user intends")
        indices = [context.selected_candidate_index] if patch.target_scope() == "selected" else range(len(context.candidates))
        for index in indices:
            candidate = context.candidates[index]
            if patch.kind in {"crop", "resize"}:
                preprocessing_target(candidate, patch.kind, patch.block_id)
                continue
            if patch.kind in {"remove_classes", "replace_classes"}:
                for label in context.classes:
                    label_pattern = re.escape(label) + r"s?\b"
                    kept = bool(re.search(r"\bkeep(?:\s+the)?\s+" + label_pattern, prompt, re.I))
                    excluded = bool(re.search(r"\b(?:instead of|stop detecting|stop counting|remove|drop)(?:\s+the)?\s+" + label_pattern, prompt, re.I))
                    if kept and ((patch.kind == "remove_classes" and label in patch.classes) or
                                 (patch.kind == "replace_classes" and label not in patch.classes)):
                        raise ValueError("The proposed classes contradict a class the user explicitly asked to keep")
                    if excluded and patch.kind == "replace_classes" and label in patch.classes:
                        raise ValueError("Replacement classes include a class the user explicitly excluded")
            if patch.kind == "count_rule":
                detectors = [block for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"}]
                if len(detectors) == 1:
                    labels = detectors[0].params.get("classes", [])
                    if isinstance(labels, list) and len(labels) > 1:
                        for raw_label in labels:
                            if isinstance(raw_label, str) and re.search(
                                r"\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                                + re.escape(raw_label) + r"s?\b", prompt, re.I
                            ) and not any(item.kind == "replace_classes" and item.classes == [raw_label] for item in decision.patches):
                                raise ValueError("Counts aggregate multiple detector classes; ask how to filter the requested class-specific count")
            if patch.kind == "eval_target":
                metric = patch.eval_metric or candidate.eval.metric
                if metric != "count_mae" and patch.eval_target is not None and patch.eval_target > 1:
                    raise ValueError("Accuracy targets use fractions in [0, 1], not percentages")
                continue
            roles = {
                "confidence": {"detect", "detect_open_vocab"}, "add_classes": {"detect", "detect_open_vocab"},
                "remove_classes": {"detect", "detect_open_vocab"}, "replace_classes": {"detect", "detect_open_vocab"},
                "count_rule": {"rule"}, "expected_text": {"match"}, "sample_fps": {"frame_sample"},
            }[patch.kind]
            matches = [block for block in candidate.blocks if block.type in roles]
            if not matches and patch.block_id is None:
                upstream = {"count_rule": {"count_per_zone"}, "expected_text": {"ocr", "barcode"}}.get(patch.kind, set())
                matches = [block for block in candidate.blocks if block.type in upstream]
                if patch.kind == "count_rule" and matches and patch.count_threshold is None:
                    raise ValueError("Adding a count rule needs the user's count threshold")
            if patch.block_id:
                matches = [block for block in matches if block.id == patch.block_id]
            if len(matches) != 1:
                raise ValueError(f"{patch.kind} has {len(matches)} plausible target blocks; ask which existing block to edit")
            if patch.kind == "remove_classes":
                current = matches[0].params.get("classes", [])
                if not isinstance(current, list) or not set(patch.classes) <= set(current):
                    raise ValueError("Remove only exact existing class names")
                if len(patch.classes) == len(current):
                    raise ValueError("A detector must retain a class; ask which class to detect instead")


def validate_comparison_event_topology(decision: RefinementDecision, prompt: str, context: RefinementContext) -> None:
    """A literal-change patch cannot silently add/remove/filter local events."""
    patches = [patch for patch in decision.patches if patch.kind == "expected_text"]
    if not patches:
        return
    # Text inside quotes is comparison data, not a request to alter event behavior.
    visible = reading_instruction_text(prompt)
    intent = event_intent(visible, parse_counts=False)
    if intent.ambiguous_negation or intent.excludes_storage:
        raise ValueError("The reading event change needs clarification; an expected-text patch cannot change storage or resolve conflicting event instructions")
    explicit_disable = intent.disabled and bool(re.search(r"\b(?:events?|flagging|flags?)\b", visible, re.I))
    if not intent.requested and not explicit_disable:
        return
    for patch in patches:
        indices = [context.selected_candidate_index] if patch.target_scope() == "selected" else range(len(context.candidates))
        for index in indices:
            candidate = context.candidates[index]
            matches = [block for block in candidate.blocks if block.type == "match"
                       and (patch.block_id is None or block.id == patch.block_id)]
            if len(matches) > 1:
                continue  # The normal target guard will request an unambiguous block.
            match = matches[0] if matches else None
            has_sink = match is not None and any(block.type == "sink_event"
                and block.inputs.get("event") == f"${match.id}.event" for block in candidate.blocks)
            if (intent.requested and not has_sink) or (explicit_disable and has_sink):
                raise ValueError("Adding or removing local event output requires a structural workflow change; an expected-text patch only changes the comparison. Ask whether to apply only the text comparison and preserve existing event behavior.")
            if intent.requested and match is not None:
                choice = PatternChoice.model_validate({"use_case": "custom", "pipeline_type": "ocr",
                    "expected_text": patch.expected_text, "match_mode": patch.match_mode or match.params.get("mode", "contains"),
                    "match_emit": match.params.get("emit", "all"), "record_events": True,
                    "metric": "text_accuracy", "target": 0.95})
                validate_reading_mode(PlanDecision(message="Preserve current event connections", choices=[choice]), prompt)
