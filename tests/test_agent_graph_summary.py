"""Completion prose describes actual graph behavior, never model assertions."""
import pytest

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision
from agent.graph_summary import describe_candidates, describe_pipeline
from agent.templates import build_template
from spec.models import BlockSpec


def test_count_only_summary_does_not_repeat_model_event_or_accuracy_claims() -> None:
    message = "Creates an alert at eight pallets, emails the team, and is 99% accurate."
    decision = PlanDecision(message=message, choices=[PatternChoice(use_case="custom", objects=["pallet"],
        metric="count_mae", target=.5, count_threshold=None)])
    before = decision.model_dump(mode="json")
    result = compile_decision(decision, "media", "fixture-color-v1")
    assert result.message == 'Displays counts of "pallet" in each processed frame.'
    assert decision.model_dump(mode="json") == before and decision.message == message
    assert not any(word in result.message.lower() for word in ("alert", "email", "accurate", "ready", "tested", "approved", "deployed"))
    assert "no event" not in result.message.lower()


@pytest.mark.parametrize("operator,phrase", [(">=", "at least"), ("<=", "at most"), (">", "more than"),
                                            ("<", "less than"), ("==", "exactly"), ("!=", "different from")])
def test_actual_count_rule_operator_threshold_duration_and_regions(operator: str, phrase: str) -> None:
    decision = PlanDecision(message="Untrusted description", choices=[PatternChoice(use_case="custom", objects=["pallet"],
        use_zones=True, zone_ids=["A", "B"], count_operator=operator, count_threshold=8, hold_seconds=12,
        metric="count_mae", target=.5)])
    result = compile_decision(decision, "media", "fixture-color-v1")
    rule = next(block for block in result.candidates[0].blocks if block.type == "rule")
    assert rule.params["when"] == f"count {operator} 8"
    assert 'in each of regions "A" and "B"' in result.message
    assert f"Creates a local event when that count stays {phrase} 8 for 12 seconds." in result.message
    assert "Untrusted description" not in result.message


def test_zero_threshold_is_not_replaced_with_one() -> None:
    decision = PlanDecision(message="Zero", choices=[PatternChoice(use_case="custom", objects=["pallet"],
        count_operator="==", count_threshold=0, metric="count_mae", target=.5)])
    result = compile_decision(decision, "media", "fixture-color-v1")
    assert next(block for block in result.candidates[0].blocks if block.type == "rule").params["when"] == "count == 0"
    assert "exactly 0" in result.message


def test_mixed_classes_are_combined_counts_with_sink_connected_rule_only() -> None:
    spec = build_template("damage", "media", "fixture-color-v1")[0]
    message = describe_pipeline(spec)
    assert 'combined count of "damaged carton" and "damaged pallet"' in message
    assert "at least 1" in message
    spec.blocks = [block for block in spec.blocks if block.type != "sink_event"]
    assert "event" not in describe_pipeline(spec).lower()


@pytest.mark.parametrize("reader,mode,expected", [("ocr", "contains", "LOT-77"), ("barcode", "exact", "SKU-042")])
def test_reading_summary_uses_actual_operator_and_literal(reader: str, mode: str, expected: str) -> None:
    spec = build_template("labels", "media", "fixture-color-v1")[0]
    next(block for block in spec.blocks if block.type == "ocr").type = reader
    check = next(block for block in spec.blocks if block.type == "match")
    check.params.update(expected=expected, mode=mode)
    summary = describe_pipeline(spec)
    assert ("Reads printed text." if reader == "ocr" else "Reads barcodes.") in summary
    assert ("contains" if mode == "contains" else "exactly matches") in summary
    assert f'"{expected}"' in summary
    spec.blocks = [block for block in spec.blocks if block.type != "sink_event"]
    summary = describe_pipeline(spec)
    assert "Reads" in summary and expected in summary and "Checks" in summary
    assert "event" not in summary


def test_rule_must_feed_sink_and_uses_actual_referenced_count_branch() -> None:
    spec = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    spec.blocks.extend([
        BlockSpec(id="other_count", type="count_per_zone", inputs={"dets": "$det.dets"}),
        BlockSpec(id="disconnected", type="rule", params={"when": "count >= 999", "hold_s": 99}, inputs={"value": "$other_count.counts"}),
        BlockSpec(id="chained_sink", type="sink_event", inputs={"event": "$out.event"}),
    ])
    summary = describe_pipeline(spec)
    assert "999" not in summary and summary.count("Creates a local event") == 1


def test_inline_regions_and_unassigned_counts_are_described_without_file_access() -> None:
    spec = build_template("pallets", "media", "fixture-color-v1")[0]
    next(block for block in spec.blocks if block.type == "zone_filter").params = {
        "zones": [{"id": "dock", "polygon": [[0, 0], [1, 0], [1, 1]]}]}
    next(block for block in spec.blocks if block.type == "count_per_zone").params["include_unassigned"] = True
    summary = describe_pipeline(spec)
    assert 'in region "dock"' in summary and "separate count outside" in summary


def test_distinct_candidates_remain_distinct_and_duplicate_summaries_collapse() -> None:
    first = build_template("pallets", "media", "fixture-color-v1")[0]
    second = first.model_copy(deep=True)
    assert describe_candidates([first, second]).startswith("Configured 2 alternatives.")
    next(block for block in second.blocks if block.type == "rule").params["hold_s"] = 30
    summary = describe_candidates([first, second])
    assert "Candidate 1:" in summary and "Candidate 2:" in summary and "30 seconds" in summary


def test_summary_is_bounded_and_deterministic_without_mutating_graph() -> None:
    spec = build_template("custom", "media", "fixture-color-v1", classes=["part-" + "x" * 80 + str(index) for index in range(20)])[0]
    before = spec.model_dump(mode="json", by_alias=True)
    one = describe_candidates([spec, spec, spec])
    assert len(one) < 6000 and "16 other classes" in one
    assert one == describe_candidates([spec, spec, spec])
    assert spec.model_dump(mode="json", by_alias=True) == before
