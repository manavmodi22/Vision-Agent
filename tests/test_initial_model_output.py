"""Model output must state reading semantics; persisted workflows keep defaults."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import plan_from_context
from agent.initial_output import ModelCustomPlanDecision, ModelPlanDecision
from agent.prompts import CUSTOM_PLANNER_V02, INITIAL_READING_EXAMPLE, PLANNER_V02
from agent.templates import build_template
from engine.blocks.params import MatchParams
from engine.compiler import compile_pipeline
from spec.planning import PlanningModelOption, PlanningOptions


@pytest.mark.parametrize("model", [ModelPlanDecision, ModelCustomPlanDecision])
def test_model_schema_requires_explicit_reading_and_event_fields(model: type[ModelPlanDecision] | type[ModelCustomPlanDecision]) -> None:
    schema = model.model_json_schema()
    name = schema["properties"]["choices"]["items"]["$ref"].split("/")[-1]
    choice = schema["$defs"][name]
    assert {"match_mode", "match_emit", "record_events", "model_capability_id", "model_reason"} <= set(choice["required"])
    for field in ("match_mode", "match_emit", "record_events", "model_capability_id", "model_reason"):
        assert "default" not in choice["properties"][field]
    assert choice["additionalProperties"] is False


@pytest.mark.parametrize("model", [ModelPlanDecision, ModelCustomPlanDecision])
@pytest.mark.parametrize("omitted", [("match_mode",), ("match_emit",), ("record_events",), ("match_mode", "match_emit", "record_events")])
def test_missing_fields_are_rejected(model: type[ModelPlanDecision] | type[ModelCustomPlanDecision], omitted: tuple[str, ...]) -> None:
    value = json.loads(INITIAL_READING_EXAMPLE.split("Return: ", 1)[1].strip().removesuffix("."))
    for field in omitted:
        value["choices"][0].pop(field)
    with pytest.raises(ValidationError) as failure:
        model.model_validate(value)
    assert {error["loc"][-1] for error in failure.value.errors() if error["type"] == "missing"} == set(omitted)


def test_persisted_choice_and_legacy_pipeline_keep_defaults(tmp_path: Path) -> None:
    old = {"use_case": "custom", "pipeline_type": "ocr", "expected_text": "ABC-990", "metric": "text_accuracy", "target": .95}
    choice = PatternChoice.model_validate(old)
    assert choice.match_mode == "contains" and choice.match_emit == "all"
    assert PlanDecision.model_validate({"message": "Saved", "choices": [old]}).choices[0] == choice
    spec = build_template("labels", "media", "fixture-color-v1")[0]
    match = next(block for block in spec.blocks if block.type == "match")
    match.params = {"expected": "ABC-990"}
    params = compile_pipeline(spec, tmp_path).params[match.id]
    assert isinstance(params, MatchParams) and params.mode == "contains" and params.emit == "all"


def test_ocr_example_compiles_explicit_model_values() -> None:
    value = json.loads(INITIAL_READING_EXAMPLE.split("Return: ", 1)[1].strip().removesuffix("."))
    output = ModelCustomPlanDecision.model_validate(value)
    typed = PlanDecision.model_validate(output.model_dump(mode="json"))
    options = PlanningOptions(snapshot_id="schema-fixture", project_id="schema-fixture", fixture_source=False,
        eligible_models=[PlanningModelOption(capability_id="model.apple-vision", model_id="apple-vision", adapter_id="apple-vision",
            task_types=["ocr", "barcode"], output_contract="texts/v1", vocabulary="not_applicable", readiness="unchecked")], blocked_options=[])
    brief = 'Read printed labels and create a local event only when the text exactly equals "ABC-990".'
    result = plan_from_context(typed, brief, "media", "fixture-color-v1", options=options)
    assert next(block for block in result.candidates[0].blocks if block.type == "match").params == {
        "expected": "ABC-990", "mode": "exact", "emit": "matched"}
    typed.choices[0].match_mode = "contains"
    with pytest.raises(ValueError, match="match_mode 'exact'"):
        plan_from_context(typed, brief, "media", "fixture-color-v1")
    assert typed.choices[0].match_mode == "contains"
    assert INITIAL_READING_EXAMPLE in PLANNER_V02 and INITIAL_READING_EXAMPLE in CUSTOM_PLANNER_V02


@pytest.mark.parametrize("model", [ModelPlanDecision, ModelCustomPlanDecision])
def test_clarification_does_not_require_choices(model: type[ModelPlanDecision] | type[ModelCustomPlanDecision]) -> None:
    result = model.model_validate({"message": "Need a value", "questions": ["Which code?"], "choices": []})
    assert result.questions and result.choices == []
