"""Comparison observations and local events have independent, explicit behavior."""
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image
from pydantic import ValidationError

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, plan_from_context
from agent.machine import AgentState
from agent.refinement_contracts import RefinementDecision, validate_refinement_intent
from agent.replay import replay_operation
from agent.state_contracts import AgentOperation, CapturedCall
from agent.task_validation import validate_output_behavior
from agent.templates import build_template
from engine.blocks.params import MatchParams
from engine.builds.refinement_edits import apply_edit
from engine.compiler import CompiledPipeline, compile_pipeline
from engine.runtime import executor
from engine.runtime.values import ExecutionState, PortValue, TextValue
from spec.models import BlockSpec, FrameResult, PipelineSpec
from spec.refinement import RefinementContext, RefinementPatch


def choice(record: bool | None, *, emit: Literal["all", "matched", "mismatched"] = "all") -> PlanDecision:
    return PlanDecision(message="Untrusted model text", choices=[PatternChoice(use_case="custom", pipeline_type="ocr",
        expected_text="ABC-990", match_mode="exact", match_emit=emit, record_events=record,
        metric="text_accuracy", target=.95)])


def inject_readings(monkeypatch: pytest.MonkeyPatch, observed: list[str]) -> None:
    original = executor.execute_block

    def reading(block: BlockSpec, inputs: dict[str, PortValue], compiled: CompiledPipeline,
                timestamp: float, state: ExecutionState) -> dict[str, PortValue]:
        if block.type in {"ocr", "barcode"}:
            return {"text": TextValue(list(observed))}
        return original(block, inputs, compiled, timestamp, state)

    monkeypatch.setattr(executor, "execute_block", reading)


@pytest.mark.parametrize("observed,matched", [(["ABC-990"], True), (["XABC-990Y"], False), ([], False)])
@pytest.mark.parametrize("emit", ["all", "matched", "mismatched"])
@pytest.mark.parametrize("record", [True, False])
def test_executed_comparison_survives_sink_and_event_filter_choices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        observed: list[str], matched: bool, emit: Literal["all", "matched", "mismatched"], record: bool) -> None:
    # Stub only recognition. Compile, graph execution, comparison, filtering and sinks are real.
    inject_readings(monkeypatch, observed)
    spec = compile_decision(choice(record, emit=emit), "media", "unused").candidates[0]
    result = executor.execute_image(compile_pipeline(spec, tmp_path), Image.new("RGB", (16, 16)),
                                    "generated-test.png", 0, ExecutionState())
    assert [row.model_dump() for row in result.comparisons] == [{"block_id": "check", "expected": "ABC-990",
        "observed": observed, "mode": "exact", "matched": matched}]
    should_emit = record and (emit == "all" or (matched if emit == "matched" else not matched))
    assert len(result.events) == int(should_emit)
    if should_emit:
        assert result.events[0]["matched"] is result.comparisons[0].matched
        assert result.events[0]["observed"] == result.comparisons[0].observed


def test_independent_match_blocks_preserve_raw_unicode_and_whitespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = [" ХABC-990Y ", "cafe\u0301", "ABC-990"]
    inject_readings(monkeypatch, observed)
    spec = compile_decision(choice(False), "media", "unused").candidates[0]
    spec.blocks.extend([
        BlockSpec(id="unicode", type="match", params={"expected": "café", "mode": "exact", "emit": "matched"}, inputs={"text": "$read.text"}),
        BlockSpec(id="literal", type="match", params={"expected": " ХABC-990Y ", "mode": "exact"}, inputs={"text": "$read.text"}),
        BlockSpec(id="substring", type="match", params={"expected": "ABC-990Y", "mode": "contains"}, inputs={"text": "$read.text"}),
    ])
    result = executor.execute_image(compile_pipeline(spec, tmp_path), Image.new("RGB", (16, 16)),
                                    "generated-test.png", 0, ExecutionState())
    assert {row.block_id: row.matched for row in result.comparisons} == {
        "check": True, "unicode": False, "literal": True, "substring": True}
    assert all(row.observed == observed for row in result.comparisons)
    assert result.events == []
    assert result.comparisons[2].expected == " ХABC-990Y "
    assert FrameResult.model_validate_json(result.model_dump_json()) == result


def test_historical_frame_has_no_invented_comparison() -> None:
    old = FrameResult.model_validate({"image_path": "old.png", "texts": ["ABC-990"], "events": []})
    assert old.comparisons == []


@pytest.mark.parametrize("brief", [
    "Read printed labels and compare against ABC-990 exactly. Do not create events or send alerts.",
    "Read printed labels and compare against ABC-990 exactly.",
    "Read printed labels and compare against ABC-990 exactly. No events.",
])
def test_new_comparison_request_does_not_acquire_local_events(brief: str) -> None:
    valid = choice(False)
    validate_output_behavior(valid, brief)
    result = plan_from_context(valid, brief, "media", "unused")
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", "ocr", "match"]
    assert 'exactly matches "ABC-990"' in result.message
    assert "event" not in result.message
    with pytest.raises(ValueError, match="record_events"):
        plan_from_context(choice(True), brief, "media", "unused")


def test_requested_reading_events_are_not_silently_dropped() -> None:
    brief = 'Read printed labels and create a local event only when the text exactly equals "ABC-990".'
    result = plan_from_context(choice(True, emit="matched"), brief, "media", "unused")
    assert any(block.type == "sink_event" for block in result.candidates[0].blocks)
    with pytest.raises(ValueError, match="record_events"):
        plan_from_context(choice(False, emit="matched"), brief, "media", "unused")
    with pytest.raises(ValidationError, match="explicit comparison"):
        PatternChoice(use_case="custom", pipeline_type="ocr", record_events=True, metric="text_accuracy", target=.95)


def test_new_comparison_rejects_conflicting_or_conditional_event_negation() -> None:
    with pytest.raises(ValueError, match="conflicting or conditional"):
        plan_from_context(choice(False), "Read text and compare against ABC-990. Don't create events unless it matches.",
                          "media", "unused")


def test_legacy_saved_decision_replays_same_implicit_sink_and_summary() -> None:
    historical = choice(None).model_dump(mode="json")
    historical["choices"][0].pop("record_events")
    decision = PlanDecision.model_validate(historical)
    result = compile_decision(decision, "media", "unused")
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", "ocr", "match", "sink_event"]
    assert result.message == 'Reads printed text. Checks whether the read text exactly matches "ABC-990".'
    result.operation_id = "old-reading-run"
    spec = result.candidates[0].model_dump(mode="json", by_alias=True)
    operation = AgentOperation(id=result.operation_id, project_id="legacy", trace_id="trace", root_span_id="root",
        owner_pid=0, deadline=0, status="completed", input_fingerprint="old", brief="Read printed labels and compare against ABC-990 exactly.",
        source_path="media", detector_model="unused", state=AgentState(), decision=decision, result=result,
        calls=[CapturedCall(id="validate", kind="tool", name="pipeline_validate", started_ns=0, ended_ns=1,
                            status="completed", request={"spec": spec}, result={"valid": True}),
               CapturedCall(id="run", kind="tool", name="pipeline_run", started_ns=2, ended_ns=3,
                            status="completed", request={"spec": spec}, result={"frames": [{"texts": ["ABC-990"]}]})])
    replay = replay_operation(operation)
    assert replay.reproduced and replay.effects_executed is False and replay.errors == []


@pytest.mark.parametrize("has_match,has_sink", [(False, False), (True, False), (True, True)])
def test_expected_text_refinement_preserves_existing_event_topology(has_match: bool, has_sink: bool) -> None:
    spec = build_template("labels", "media", "unused")[0]
    spec.blocks = [block for block in spec.blocks if (has_match or block.type != "match") and (has_sink or block.type != "sink_event")]
    sinks = [block.model_dump(mode="json", by_alias=True) for block in spec.blocks if block.type == "sink_event"]
    apply_edit(spec, RefinementPatch(kind="expected_text", expected_text=" XABC-990Y ", match_mode="exact"), {})
    assert [block.model_dump(mode="json", by_alias=True) for block in spec.blocks if block.type == "sink_event"] == sinks
    match = next(block for block in spec.blocks if block.type == "match")
    assert MatchParams.model_validate(match.params).expected == " XABC-990Y "
    assert "Checks whether" in compile_decision(choice(False), "media", "unused").message


def test_plain_reading_graph_has_no_comparisons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inject_readings(monkeypatch, ["ABC-990"])
    spec = PipelineSpec.model_validate({"name": "Read only", "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "read", "type": "ocr", "in": {"image": "$sample.frame"}}],
        "eval": {"metric": "text_accuracy", "target": .95}})
    result = executor.execute_image(compile_pipeline(spec, tmp_path), Image.new("RGB", (16, 16)),
                                    "generated-test.png", 0, ExecutionState())
    assert result.texts == ["ABC-990"] and result.comparisons == [] and result.events == []


def refinement_context(*, match: bool, sink: bool, emit: str = "all") -> RefinementContext:
    candidate = build_template("labels", "media", "unused")[0]
    candidate.blocks = [block for block in candidate.blocks if (match or block.type != "match") and (sink or block.type != "sink_event")]
    for block in candidate.blocks:
        if block.type == "match":
            block.params["emit"] = emit
    return RefinementContext(candidates=[candidate], selected_candidate_index=0, current_goal="Read labels", conversation=[],
                             classes=[], saved_zone_ids=[], clarification_count=0)


def text_refinement() -> RefinementDecision:
    return RefinementDecision(message="Change comparison", questions=[],
        patches=[RefinementPatch(kind="expected_text", expected_text="ABC-990", match_mode="exact")])


@pytest.mark.parametrize("match", [True, False])
def test_refinement_cannot_hide_requested_event_creation_in_a_literal_patch(match: bool) -> None:
    context = refinement_context(match=match, sink=False)
    with pytest.raises(ValueError, match="structural workflow change"):
        validate_refinement_intent(text_refinement(),
            'Compare against "ABC-990" exactly and create a local event when it matches.', context)
    validate_refinement_intent(text_refinement(), 'Compare against "ABC-990" exactly; do not create events.', context)


def test_refinement_cannot_hide_event_removal_or_filter_change_in_a_literal_patch() -> None:
    context = refinement_context(match=True, sink=True)
    with pytest.raises(ValueError, match="structural workflow change"):
        validate_refinement_intent(text_refinement(), 'Compare against "ABC-990" exactly; stop creating events.', context)
    with pytest.raises(ValueError, match="match_emit"):
        validate_refinement_intent(text_refinement(),
            'Compare against "ABC-990" exactly and create a local event only when it matches.', context)
    validate_refinement_intent(text_refinement(), 'Compare against "ABC-990" exactly.', context)
    validate_refinement_intent(text_refinement(), 'Compare against "ABC-990" exactly. No external alerts.', context)
    selected = refinement_context(match=True, sink=True, emit="matched")
    validate_refinement_intent(text_refinement(),
        'Compare against "ABC-990" exactly and create a local event only when it matches.', selected)


def test_fresh_detection_event_policy_cannot_drop_or_invent_a_count_trigger() -> None:
    fields = {"use_case": "custom", "objects": ["pallet"], "metric": "count_mae", "target": .5}
    with pytest.raises(ValidationError, match="explicit count condition"):
        PatternChoice.model_validate({**fields, "record_events": True})
    with pytest.raises(ValidationError, match="non-event detection pattern"):
        PatternChoice.model_validate({**fields, "record_events": False, "count_threshold": 1})
    assert PatternChoice.model_validate({**fields, "record_events": False}).count_threshold is None
    assert PatternChoice.model_validate({**fields, "record_events": True, "count_threshold": 0}).count_threshold == 0


@pytest.mark.parametrize("literal", ["create events", "do not save evidence", "Don't create events unless it matches"])
def test_quoted_comparison_values_cannot_request_event_actions(literal: str) -> None:
    decision = choice(False)
    decision.choices[0].expected_text = literal
    brief = f'Read labels and compare against "{literal}" exactly.'
    validate_output_behavior(decision, brief)
    result = plan_from_context(decision, brief, "media", "unused")
    assert not any(block.type == "sink_event" for block in result.candidates[0].blocks)
    assert next(block for block in result.candidates[0].blocks if block.type == "match").params["expected"] == literal


def test_refinement_contraction_is_not_misread_as_a_quoted_literal() -> None:
    with pytest.raises(ValueError, match="structural workflow change"):
        validate_refinement_intent(text_refinement(),
            "Don't create events. Compare against 'ABC-990' exactly.", refinement_context(match=True, sink=True))
