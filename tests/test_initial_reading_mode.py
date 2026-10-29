"""Initial reading comparisons preserve their operator, literal, and event condition."""
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, plan_from_context
from agent.task_validation import (
    explicit_expected_text,
    validate_custom_inputs,
    validate_output_behavior,
    validate_reading_mode,
)
from engine.compiler import compile_pipeline
from engine.runtime.executor import execute_block
from engine.runtime.values import EventValue, ExecutionState, TextValue


def decision(mode: Literal["contains", "exact"] = "contains", expected: str | None = "ABC-990",
             reader: Literal["ocr", "barcode"] = "barcode",
             emit: Literal["all", "matched", "mismatched"] = "all") -> PlanDecision:
    return PlanDecision(message="Untrusted model summary", choices=[PatternChoice(
        use_case="custom", pipeline_type=reader, expected_text=expected, match_mode=mode,
        match_emit=emit, metric="text_accuracy", target=.95)])


@pytest.mark.parametrize("comparison", ["exactly equals ABC-990", "equals ABC-990",
    "exactly matches ABC-990", "matches ABC-990 exactly", "has an exact match for ABC-990"])
def test_explicit_equality_rejects_contains_without_repair(comparison: str) -> None:
    brief = "Read barcodes and check whether the code " + comparison + "."
    wrong = decision("contains")
    with pytest.raises(ValueError, match="match_mode 'exact'"):
        validate_custom_inputs(wrong, brief, [])
    with pytest.raises(ValueError, match="match_mode 'exact'"):
        plan_from_context(wrong, brief, "media", "fixture-color-v1")
    assert wrong.choices[0].match_mode == "contains"
    validate_custom_inputs(decision("exact"), brief, [])


@pytest.mark.parametrize("comparison", ["contains ABC-990", "includes the substring ABC-990",
    "has a partial match for ABC-990"])
def test_explicit_substring_rejects_exact(comparison: str) -> None:
    brief = "Read printed text and check whether it " + comparison + "."
    validate_custom_inputs(decision("contains", reader="ocr"), brief, [])
    with pytest.raises(ValueError, match="match_mode 'contains'"):
        validate_custom_inputs(decision("exact", reader="ocr"), brief, [])


def test_mode_words_in_literals_are_data_and_default_remains_contains() -> None:
    for literal in ("exact", "contains", "EXACT-990", "CONTAINS-001"):
        validate_custom_inputs(decision("contains", literal), f'Read labels and check for "{literal}".', [])
    result = compile_decision(decision(), "media", "fixture-color-v1")
    comparison = next(block for block in result.candidates[0].blocks if block.type == "match")
    assert comparison.params["mode"] == "contains" and comparison.params["emit"] == "all"
    read_only = compile_decision(decision(expected=None), "media", "fixture-color-v1")
    assert {block.type for block in read_only.candidates[0].blocks} == {"frame_sample", "barcode"}


def test_conflicting_modes_need_a_question_not_a_guessed_graph() -> None:
    brief = "Read barcodes and check for exact matching and substring matching of ABC-990."
    with pytest.raises(ValueError, match="conflicting exact and contains"):
        validate_reading_mode(decision(), brief)
    validate_reading_mode(PlanDecision(message="Clarify", questions=["Use exact or contains matching?"]), brief)


@pytest.mark.parametrize("reader", ["ocr", "barcode"])
@pytest.mark.parametrize("mode", ["exact", "contains"])
@pytest.mark.parametrize("emit", ["all", "matched", "mismatched"])
def test_executable_comparison_and_event_emission(tmp_path: Path, reader: Literal["ocr", "barcode"],
        mode: Literal["exact", "contains"], emit: Literal["all", "matched", "mismatched"]) -> None:
    media = tmp_path / "media"
    media.mkdir()
    Image.new("RGB", (16, 16)).save(media / "frame.png")
    spec = compile_decision(decision(mode, reader=reader, emit=emit), "media", "fixture-color-v1").candidates[0]
    compiled = compile_pipeline(spec, tmp_path)
    block = next(block for block in spec.blocks if block.type == "match")
    assert block.params == {"expected": "ABC-990", "mode": mode, "emit": emit}
    # Reader output is supplied directly; this tests match execution, not OCR quality.
    for text, matched in (("ABC-990", True), ("prefix ABC-990 suffix", mode == "contains"), ("OTHER", False)):
        result = execute_block(block, {"text": TextValue([text])}, compiled, 0, ExecutionState())["event"]
        assert isinstance(result, EventValue)
        should_emit = emit == "all" or (matched if emit == "matched" else not matched)
        assert len(result.events) == int(should_emit)
        if should_emit:
            assert result.events[0]["matched"] is matched
            assert result.events[0]["expected"] == "ABC-990"


@pytest.mark.parametrize("condition,emit", [("exactly equals", "matched"),
    ("does not exactly match", "mismatched"), ("mismatches", "mismatched")])
def test_conditional_event_policy_cannot_be_silently_omitted(condition: str, emit: Literal["matched", "mismatched"]) -> None:
    brief = f"Read barcodes and create an event when code {condition} ABC-990."
    mode = "exact" if "exactly" in condition else "contains"
    valid = decision(mode, emit=emit)
    validate_reading_mode(valid, brief)
    with pytest.raises(ValueError, match="match_emit"):
        validate_reading_mode(decision(mode, emit="all"), brief)
    with pytest.raises(ValueError, match="match_emit"):
        validate_reading_mode(decision(mode, emit="mismatched" if emit == "matched" else "matched"), brief)
    spec = plan_from_context(valid, brief, "media", "fixture-color-v1").candidates[0]
    assert next(block for block in spec.blocks if block.type == "match").params["emit"] == emit
    summary = compile_decision(valid, "media", "fixture-color-v1").message
    assert ("only when that comparison matches" if emit == "matched" else "only when that comparison does not match") in summary


def test_plain_check_whether_preserves_all_results() -> None:
    brief = "Read barcodes and check whether the code contains ABC-990."
    validate_reading_mode(decision(), brief)
    with pytest.raises(ValueError, match="match_emit 'all'"):
        validate_reading_mode(decision(emit="matched"), brief)


def test_old_graph_without_emit_keeps_both_comparison_results(tmp_path: Path) -> None:
    spec = compile_decision(decision(), "media", "fixture-color-v1").candidates[0]
    block = next(block for block in spec.blocks if block.type == "match")
    block.params.pop("emit")
    compiled = compile_pipeline(spec, tmp_path)
    for text in ("ABC-990", "OTHER"):
        value = execute_block(block, {"text": TextValue([text])}, compiled, 0, ExecutionState())["event"]
        assert isinstance(value, EventValue) and len(value.events) == 1


@pytest.mark.parametrize("placeholder", ["expected SKU", "correct package code", "SKU-001", None])
def test_unresolved_value_requires_clarification_even_if_model_invents_one(placeholder: str | None) -> None:
    for brief in ("Read these labels and compare them against the expected SKU.",
                  "Check whether each barcode matches the correct package code."):
        result = plan_from_context(decision(expected=placeholder), brief, "media", "fixture-color-v1")
        assert result.questions and not result.candidates


@pytest.mark.parametrize("literal", ["expected SKU", "correct code", "ABC-990"])
def test_quoted_literal_is_not_an_unresolved_placeholder(literal: str) -> None:
    brief = f'Read barcodes and compare them against "{literal}".'
    result = plan_from_context(decision(expected=literal), brief, "media", "fixture-color-v1")
    validate_custom_inputs(decision(expected=literal), brief, [])
    assert result.candidates and not result.questions


@pytest.mark.parametrize("answer,expected", [("ABC-990", "ABC-990"), ("90210", "90210"),
    ("001234567890", "001234567890"), ("APPLE", "APPLE"), ("SKU001", "SKU001"),
    ('"expected SKU"', "expected SKU"), ("The expected code is ABC-990.", "ABC-990")])
def test_explicit_clarification_supplies_value_and_preserves_it(answer: str, expected: str) -> None:
    brief = "Read these labels and compare them against the expected SKU.\nUser clarification: " + answer
    result = plan_from_context(decision(expected=expected), brief, "media", "fixture-color-v1")
    assert result.candidates and not result.questions
    with pytest.raises(ValueError, match="expected text"):
        validate_custom_inputs(decision(expected="WRONG"), brief, [])


@pytest.mark.parametrize("literal", ["001234567890", "00000", "99999", "SKU001", "APPLE"])
@pytest.mark.parametrize("phrasing", ["Read barcodes and check for {literal}.",
    "Read barcodes; the expected code is {literal}.",
    "Read barcodes and compare them against {literal}."])
def test_supplied_bare_identifiers_and_numeric_values_never_become_placeholders(literal: str, phrasing: str) -> None:
    brief = phrasing.format(literal=literal)
    assert explicit_expected_text(brief) == literal
    valid = decision(expected=literal)
    validate_custom_inputs(valid, brief, [])
    result = plan_from_context(valid, brief, "media", "fixture-color-v1")
    assert result.candidates and not result.questions
    assert next(block for block in result.candidates[0].blocks if block.type == "match").params["expected"] == literal
    with pytest.raises(ValueError, match="expected text"):
        validate_custom_inputs(decision(expected="wrong"), brief, [])


@pytest.mark.parametrize("answer", ["the expected SKU", "correct package code", "expected", "TBD", "unknown"])
def test_bare_generic_clarification_is_still_unresolved(answer: str) -> None:
    brief = "Read barcodes and compare them against the expected code.\nUser clarification: " + answer
    result = plan_from_context(decision(expected=answer), brief, "media", "fixture-color-v1")
    assert result.questions and not result.candidates
    quoted = brief.rsplit("User clarification:", 1)[0] + 'User clarification: "' + answer + '"'
    assert explicit_expected_text(quoted) == answer
    assert plan_from_context(decision(expected=answer), quoted, "media", "fixture-color-v1").candidates


@pytest.mark.parametrize("brief", ["Read labels and compare them.", "Read barcodes and check their validity.",
    "Read printed text and verify the label."])
def test_invented_literal_is_rejected_without_relying_on_placeholder_keywords(brief: str) -> None:
    with pytest.raises(ValueError, match="absent from the brief"):
        validate_custom_inputs(decision(expected="INVENTED-001"), brief, [])
    result = plan_from_context(decision(expected="INVENTED-001"), brief, "media", "fixture-color-v1")
    assert result.questions and not result.candidates


@pytest.mark.parametrize("literal", ["001234567890", "99999"])
def test_numeric_barcode_event_does_not_become_an_object_count(literal: str) -> None:
    brief = f"Read barcodes and create an event when the code exactly equals {literal}."
    valid = decision("exact", literal, emit="matched")
    validate_output_behavior(valid, brief)
    validate_custom_inputs(valid, brief, [])
    assert plan_from_context(valid, brief, "media", "fixture-color-v1").candidates


@pytest.mark.parametrize("literal,prefix", [("https://example.com/item", "https"),
    ("Authorized Personnel Only", "Authorized"), ("ABC/123", "ABC"),
    ("SKU.001", "SKU"), ("APPLE JUICE", "APPLE")])
def test_unrecognized_complete_literal_never_accepts_its_prefix(literal: str, prefix: str) -> None:
    brief = f"Read printed labels and check for {literal}."
    assert explicit_expected_text(brief) is None
    for proposed in (literal, prefix):
        result = plan_from_context(decision(expected=proposed), brief, "media", "fixture-color-v1")
        assert result.questions and not result.candidates
    quoted = f'Read printed labels and check for "{literal}".'
    assert explicit_expected_text(quoted) == literal
    validate_custom_inputs(decision(expected=literal), quoted, [])
    assert plan_from_context(decision(expected=literal), quoted, "media", "fixture-color-v1").candidates


@pytest.mark.parametrize("brief", ["Read barcodes and show the decoded codes. No expected code or comparison.",
    "Read package labels and show their codes.", "Read the printed text without comparison.",
    "Read barcodes. Don't compare or check them against anything."])
@pytest.mark.parametrize("invented", ["expected code", "comparison", "SKU001"])
def test_read_only_goal_cannot_acquire_a_comparison_even_when_placeholder_occurs_in_brief(brief: str, invented: str) -> None:
    with pytest.raises(ValueError, match="read-only task.*expected_text must be null"):
        validate_custom_inputs(decision(expected=invented), brief, [])
    with pytest.raises(ValueError, match="read-only task.*expected_text must be null"):
        plan_from_context(decision(expected=invented), brief, "media", "fixture-color-v1")
    valid = decision(expected=None)
    validate_custom_inputs(valid, brief, [])
    result = plan_from_context(valid, brief, "media", "fixture-color-v1")
    assert result.candidates and not result.questions
    assert {block.type for block in result.candidates[0].blocks} == {"frame_sample", "barcode"}


def test_exact_mode_does_not_weaken_existing_literal_preservation() -> None:
    brief = "Read barcodes and create an event when code exactly equals ABC-990."
    with pytest.raises(ValueError, match="expected text 'ABC-990'"):
        validate_custom_inputs(decision("exact", "ABC-991", emit="matched"), brief, [])
