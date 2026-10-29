"""Preserve each reader's comparison independently of other inference branches."""
import re

from agent.contracts import PatternChoice, PlanDecision
from agent.task_validation import (
    explicit_expected_text,
    reading_instruction_text,
    validate_custom_inputs,
)

_COMPARISON = r"\b(?:check|verify|(?:mis)?match(?:es|ing)?|compare|comparison|expected|contains?|equals?)\b"


def event_request_text(request: str) -> str:
    # "Do not crop" prohibits an image transform. "Do not save crops" still
    # prohibits evidence retention and must keep the existing storage guard.
    visible = reading_instruction_text(request)
    spans = list(re.finditer(r"\b(?:do not|don't|never)\s+(crop)\b", visible, re.I))
    for match in reversed(spans):
        request = request[:match.start(1)] + "transform" + request[match.end(1):]
    return request


def comparison_requested(request: str) -> bool:
    visible = reading_instruction_text(request)
    return bool(re.search(_COMPARISON, visible, re.I)) and not bool(re.search(
        r"\b(?:no|without)\s+(?:a\s+|an\s+|any\s+)?(?:expected|comparison|matching)|\b(?:do not|don't)\s+(?:compare|match|check)", visible, re.I))


def validate_reader_branch(choice: PatternChoice, request: str) -> None:
    """Ambiguous comparisons require a question; another task cannot hide one."""
    visible = reading_instruction_text(request)
    if comparison_requested(request):
        expected = explicit_expected_text(request)
        literals = re.findall(r'"([^"\n]{1,256})"|“([^”\n]{1,256})”|(?<!\w)\x27([^\x27\n]{1,256})\x27', request)
        values = {next(value for value in match if value) for match in literals}
        if expected is None and len(values) == 1:
            expected = next(iter(values))
        if expected is None:
            raise ValueError("The reader comparison needs one explicit expected value; ask rather than omitting it or inventing a literal")
        if choice.expected_text != expected:
            raise ValueError("Preserve the requested reader comparison and its exact expected value on this branch")
        exact = bool(re.search(r"\b(?:exact|exactly|equals?|equality)\b", visible, re.I))
        contains = bool(re.search(r"\b(?:contains?|substring|partial\s+match(?:ing)?)\b", visible, re.I))
        if exact and contains:
            raise ValueError("Specify exact equality or substring comparison for this reader")
        mode = "exact" if exact else "contains"
        if choice.match_mode != mode:
            raise ValueError(f"The requested reader comparison requires match_mode {mode!r}")
    elif choice.expected_text is not None:
        raise ValueError("No comparison was requested for this reader branch; preserve read-only output")
    validate_custom_inputs(PlanDecision(message="Validate this reader branch", choices=[choice]), event_request_text(request), [])
