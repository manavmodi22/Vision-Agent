"""User intent, comparison operators and time units survive model decisions."""
from pathlib import Path

import pytest

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, require_complete_alert
from agent.event_intent import event_intent, number
from agent.task_validation import validate_event_values, validate_output_behavior
from engine.runtime import run_pipeline
from engine.runtime.fixtures import generate_demo


def decision(threshold: int | None, operator: str = ">=", hold: float = 0) -> PlanDecision:
    return PlanDecision(message="Untrusted model description", choices=[PatternChoice.model_validate({
        "use_case": "custom", "objects": ["pallet"], "metric": "count_mae", "target": .5,
        "count_threshold": threshold, "count_operator": operator, "hold_seconds": hold,
    })])


@pytest.mark.parametrize("brief,threshold,operator,seconds", [
    ("Count pallets and create a local event when there are at least eight pallets for twelve seconds.", 8, ">=", 12),
    ("Flag a lane when count > 5 for two minutes.", 5, ">", 120),
    ("Create an event when there are at most zero pallets.", 0, "<=", 0),
    ("Flag when count == 0 for zero seconds.", 0, "==", 0),
    ("Flag a lane when there are fewer than eleven pallets for ninety seconds.", 11, "<", 90),
    ("Create events when count != three for one minute.", 3, "!=", 60),
    ("Save evidence when there are no more than twenty-one pallets.", 21, "<=", 0),
    ("Flag a lane when there are not less than twelve pallets.", 12, ">=", 0),
    ("Create events when count >= one hundred and five for .5 minutes.", 105, ">=", 30),
    ("Save evidence when either damaged item appears.", 1, ">=", 0),
    ("Detect pallets and create a local event whenever one appears.", 1, ">=", 0),
])
def test_explicit_event_values_are_bound_exactly(brief: str, threshold: int, operator: str, seconds: float) -> None:
    actual = decision(threshold, operator, seconds)
    validate_event_values(actual, brief)
    assert require_complete_alert(actual, brief) == actual
    with pytest.raises(ValueError, match="count"):
        validate_event_values(decision(threshold + 1, operator, seconds), brief)
    with pytest.raises(ValueError, match="count"):
        validate_event_values(decision(None, operator, seconds), brief)
    with pytest.raises(ValueError, match="duration"):
        validate_event_values(decision(threshold, operator, seconds + 1), brief)
    wrong_operator = ">" if operator != ">" else ">="
    with pytest.raises(ValueError, match="count_operator"):
        validate_event_values(decision(threshold, wrong_operator, seconds), brief)


def test_fourteen_billion_model_threshold_one_with_correct_hold_is_rejected() -> None:
    brief = "Count pallets in saved lanes A and B and flag a lane when it has at least 8 pallets for 12 seconds."
    wrong = decision(1, hold=12)
    with pytest.raises(ValueError, match="count >= 8"):
        validate_output_behavior(wrong, brief)
    with pytest.raises(ValueError, match="already-supplied"):
        require_complete_alert(wrong, brief)
    assert wrong.choices[0].count_threshold == 1, "Validation must not silently repair the model decision"


@pytest.mark.parametrize("ending", ["No events.", "Without alerts.", "Don't create any events.",
    "Disable notifications.", "Don't flag anything.", "Show counts only."])
def test_negative_event_requests_remain_count_only(ending: str) -> None:
    brief = "Count pallets. " + ending
    plain = decision(None)
    validate_output_behavior(plain, brief)
    assert require_complete_alert(plain, brief) == plain
    with pytest.raises(ValueError, match="without an event trigger"):
        validate_output_behavior(decision(1), brief)


def test_event_nouns_in_object_names_do_not_invent_event_behavior() -> None:
    for brief in ("Count event badges.", "Detect the class flag.", "Count pallets."):
        assert not event_intent(brief).requested
        validate_event_values(decision(None), brief)
        with pytest.raises(ValueError, match="without an event trigger"):
            validate_event_values(decision(1), brief)


def test_local_evidence_can_coexist_with_no_external_alerts() -> None:
    brief = "Find pallets. No alerts, but save local evidence whenever one appears."
    validate_event_values(decision(1), brief)


def test_conditional_negation_is_not_silently_treated_as_no_events() -> None:
    brief = "Don't create events unless count >= five."
    with pytest.raises(ValueError, match="conditional negation"):
        validate_event_values(decision(None), brief)
    with pytest.raises(ValueError, match="conditional negation"):
        validate_event_values(decision(5), brief)


def test_unknown_full_capacity_asks_even_if_model_invents_one() -> None:
    brief = "Count pallets and alert when a lane is full."
    for threshold in (None, 1, 9):
        result = require_complete_alert(decision(threshold), brief)
        assert result.questions == ["How many pallets make a lane full?"] and not result.choices
    specified = brief + " User clarification: eleven pallets."
    assert not require_complete_alert(decision(11), specified).questions
    with pytest.raises(ValueError, match="count >= 11"):
        require_complete_alert(decision(1), specified)
    assert require_complete_alert(decision(None), "Count pallets. No alerts even when full.").choices


def test_duration_and_metric_numbers_do_not_become_count_thresholds() -> None:
    brief = "Create an event when there are at least eight pallets for at least twelve seconds. Use recall at least 0.9."
    intent = event_intent(brief)
    assert intent.comparison == (">=", 8) and intent.hold_seconds == 12
    unknown = "Count pallets and alert when full for twelve seconds."
    assert event_intent(unknown).unknown_full
    assert require_complete_alert(decision(12, hold=12), unknown).questions


@pytest.mark.parametrize("brief", ["Create events when count >= 5 and count <= 9.",
    "Flag when count > 3 for two seconds and for three minutes.",
    "Create events when count > 10001.", "Flag when count > 1 for sixty-one minutes."])
def test_unrepresentable_or_out_of_bounds_conditions_fail_clearly(brief: str) -> None:
    with pytest.raises(ValueError):
        validate_event_values(decision(1), brief)
    # A genuine question can resolve the unsupported request without a guessed graph.
    validate_event_values(PlanDecision(message="Clarify", questions=["Which one supported condition should I use?"]), brief)


@pytest.mark.parametrize("word,value", [("eleven", 11), ("twenty-one", 21), ("ninety", 90),
    ("one hundred and five", 105), ("one thousand two hundred and three", 1203), ("a dozen", 12), ("half", .5)])
def test_bounded_spelled_quantity_conversion(word: str, value: float) -> None:
    assert number(word) == value


def test_zero_and_operator_reach_executable_graph_without_coercion(tmp_path: Path) -> None:
    generate_demo(tmp_path)
    actual = decision(0, "<=")
    validate_event_values(actual, "Create an event when count <= zero.")
    candidate = compile_decision(actual, "media", "fixture-color-v1").candidates[0]
    rule = next(block for block in candidate.blocks if block.type == "rule")
    assert rule.params["when"] == "count <= 0"
    assert not run_pipeline(candidate, tmp_path, max_frames=1).frames[0].events
    # count >= 0 has different behavior; preserve it rather than coercing zero to one.
    other = compile_decision(decision(0, ">="), "media", "fixture-color-v1").candidates[0]
    assert run_pipeline(other, tmp_path, max_frames=1).frames[0].events


def test_explicit_local_event_is_preserved_while_external_alerts_are_disabled(tmp_path: Path) -> None:
    generate_demo(tmp_path)
    brief = "Create a local event at5 pallets, but no external alerts."
    choice = decision(5)
    validate_event_values(choice, brief)
    assert require_complete_alert(choice, brief) == choice
    candidate = compile_decision(choice, "media", "fixture-color-v1").candidates[0]
    assert any(block.type == "rule" and block.params["when"] == "count >= 5" for block in candidate.blocks)
    sinks = [block for block in candidate.blocks if block.type == "sink_event"]
    assert sinks and all(block.params.get("alert") is None for block in sinks)
    assert any(frame.events for frame in run_pipeline(candidate, tmp_path, max_frames=2).frames)
    validate_event_values(decision(None), "Count pallets only, no external alerts.")
