import pytest
from pydantic import ValidationError

from agent.contracts import CustomPlanDecision, PatternChoice, PlanDecision
from agent.decisions import compile_decision, require_complete_alert
from agent.task_validation import validate_custom_inputs, validate_explicit_metric


def test_model_decision_compiles_selected_parameters_without_free_graph_generation() -> None:
    decision = PlanDecision(message="Capacity is twelve pallets.", choices=[PatternChoice(
        use_case="pallets", objects=["pallet"], count_threshold=12,
        metric="count_mae", target=0.3, min_confidence=0.65,
    )])
    result = compile_decision(decision, "media", "owlv2-base-patch16")
    candidate = result.candidates[0]
    assert candidate.eval.target == 0.3
    assert next(block for block in candidate.blocks if block.type == "rule").params["when"] == "count >= 12"
    detector = next(block for block in candidate.blocks if block.type == "detect")
    assert detector.params["model"] == "owlv2-base-patch16"
    assert detector.params["min_conf"] == 0.65
    assert 'Displays counts of "pallet"' in result.message
    assert "at least 12" in result.message


def test_count_only_has_no_invented_capacity() -> None:
    result = compile_decision(PlanDecision(message="Count only.", choices=[PatternChoice(
        use_case="pallets", metric="count_mae", target=0.5,
    )]), "media", "fixture-color-v1")
    assert "rule" not in {block.type for block in result.candidates[0].blocks}


def test_label_target_must_come_from_model_decision_not_default_template() -> None:
    with pytest.raises(ValidationError, match="expected_text"):
        PatternChoice(use_case="labels", metric="text_accuracy", target=0.95)
    result = compile_decision(PlanDecision(message="Check specified SKU.", choices=[PatternChoice(
        use_case="labels", metric="text_accuracy", target=0.95, expected_text="ITEM-882",
    )]), "media", "fixture-color-v1")
    assert next(block for block in result.candidates[0].blocks if block.type == "match").params["expected"] == "ITEM-882"


def test_clarification_has_no_synthetic_candidate_fallback() -> None:
    result = compile_decision(PlanDecision(message="Need SKU.", questions=["What SKU should I check?"]), "media", "fixture-color-v1")
    assert result.candidates == []
    assert result.questions == ["What SKU should I check?"]


def test_required_alert_cannot_be_silently_dropped_by_count_only_model_choice() -> None:
    decision = PlanDecision(message="Count pallets.", choices=[PatternChoice(
        use_case="pallets", metric="count_mae", target=0.5,
    )])
    checked = require_complete_alert(decision, "Count pallets and alert when a lane is full.")
    assert checked.choices == []
    assert checked.questions == ["How many pallets make a lane full?"]
    assert require_complete_alert(decision, "Count pallets without alerts.") == decision
    assert require_complete_alert(decision, "Previous conversation:\nalert when full\nUser request:\nCount only, no alerts.") == decision


def test_custom_application_uses_user_classes_without_a_warehouse_preset() -> None:
    decision = PlanDecision(message="Inspect components.", choices=[PatternChoice(
        use_case="custom", objects=["bolt", "washer"], min_confidence=0.3,
        count_threshold=1, metric="recall", target=0.85,
    )])
    result = compile_decision(decision, "media", "owlv2-base-patch16")
    detector = next(block for block in result.candidates[0].blocks if block.type == "detect")
    assert detector.params["classes"] == ["bolt", "washer"]
    assert result.candidates[0].eval.target == 0.85
    with pytest.raises(ValidationError):
        CustomPlanDecision.model_validate({"message": "Unrelated example", "choices": [{
            "use_case": "pallets", "objects": ["pallet"], "metric": "count_mae", "target": 0.5,
        }]})


def test_custom_barcode_reader_is_a_graph_choice_not_an_object_label() -> None:
    decision = PlanDecision(message="Read package code.", choices=[PatternChoice(
        use_case="custom", pipeline_type="barcode", expected_text="ABC-990",
        metric="text_accuracy", target=0.95,
    )])
    result = compile_decision(decision, "media", "owlv2-base-patch16")
    assert "barcode" in {block.type for block in result.candidates[0].blocks}
    assert "detect" not in {block.type for block in result.candidates[0].blocks}


def test_explicit_user_metric_confidence_and_ontology_are_not_replaced_by_defaults() -> None:
    decision = PlanDecision(message="Detect.", choices=[PatternChoice(
        use_case="custom", objects=["person"], min_confidence=0.4, metric="count_mae", target=0.5,
    )])
    with pytest.raises(ValueError, match="recall target 0.9"):
        validate_explicit_metric(decision, "Evaluate recall target 0.9")
    with pytest.raises(ValueError, match="confidence 0.25"):
        validate_custom_inputs(decision, "Use confidence 0.25", ["person"])
    with pytest.raises(ValueError, match="ontology"):
        validate_custom_inputs(decision, "Detect", ["forklift"])


def test_custom_nonspatial_goal_cannot_acquire_saved_region_filter() -> None:
    from agent.task_validation import validate_spatial_intent
    decision = PlanDecision(message="Find damage", choices=[PatternChoice(
        use_case="custom", objects=["damaged carton", "damaged pallet"], use_zones=True,
        count_threshold=1, metric="recall", target=.9,
    )])
    with pytest.raises(ValueError, match="did not request any spatial"):
        validate_spatial_intent(decision, "Find damaged cartons and damaged pallets for review; save evidence when either appears.")
    validate_spatial_intent(decision, "Find damaged cartons inside the marked loading area.")


@pytest.mark.parametrize("expected", [None, "WRONG-001"])
def test_reading_decision_preserves_explicit_expected_code(expected: str | None) -> None:
    choice = PatternChoice(use_case="custom", pipeline_type="ocr", expected_text=expected,
                           metric="text_accuracy", target=.97)
    decision = PlanDecision(message="Read the label", choices=[choice])
    with pytest.raises(ValueError, match="explicitly supplied expected text"):
        validate_custom_inputs(decision, "Read printed labels and check for ITEM-882. Evaluate text_accuracy target 0.97.", [])
    choice.expected_text = "ITEM-882"
    validate_custom_inputs(decision, "Read printed labels and check for ITEM-882.", [])


def test_expected_value_guard_does_not_invent_an_unspecified_sku() -> None:
    from agent.task_validation import explicit_expected_text
    assert explicit_expected_text("Read these labels and compare them against the expected SKU.") is None
    assert explicit_expected_text("Read SKU-001 and show the text.") is None
    assert explicit_expected_text('Read text and check for "Authorized Personnel Only".') == "Authorized Personnel Only"
