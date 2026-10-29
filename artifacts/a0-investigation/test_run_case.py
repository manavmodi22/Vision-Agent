"""Pure evaluator checks: no model, app service, worker, or live inference."""
import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scene_case_harness", HERE / "run_case.py")
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
REFERENCE = json.loads((HERE / "cases/bus-destination-v1/manifest.json").read_text())["reference_evaluator_only"]


def preview():
    return {"frames": [{"texts": ["43", "PLYMOUTH SKI CENTRE"], "inferences": [{
        "block_id": "read_display", "input_to_frame": [.5, 0, .5, 1],
        "result": {"readings": [
            {"text": "43", "box": [.28, .27, .36, .32]},
            {"text": "PLYMOUTH SKI CENTRE", "box": [.4, .27, .62, .33]},
        ]}}]}]}


def test_grouped_words_and_right_crop_map_to_original_display():
    result = HARNESS.score_preview(preview(), REFERENCE)
    assert result["predeclared_preview_check_passed"]
    assert result["readings"][0]["source_box"] == [.64, .27, .6799999999999999, .32]
    assert result["actual_tokens"] == ["43", "PLYMOUTH", "SKI", "CENTRE"]


def test_exact_words_elsewhere_do_not_satisfy_reference_geometry():
    value = preview()
    value["frames"][0]["inferences"][0]["input_to_frame"] = [0, 0, 1, 1]
    result = HARNESS.score_preview(value, REFERENCE)
    assert result["exact_tokens"] and not result["geometry_inside_display"]
    assert not result["predeclared_preview_check_passed"]


def test_case_and_duplicates_are_not_repaired():
    for texts in [["43", "Plymouth SKI CENTRE"], ["43", "43", "PLYMOUTH SKI CENTRE"]]:
        value = preview()
        value["frames"][0]["texts"] = texts
        assert not HARNESS.score_preview(value, REFERENCE)["predeclared_preview_check_passed"]


def test_missing_geometry_or_missing_preview_is_not_a_pass():
    value = preview()
    value["frames"][0]["inferences"][0]["result"]["readings"][0]["box"] = None
    assert not HARNESS.score_preview(value, REFERENCE)["predeclared_preview_check_passed"]
    result = HARNESS.score_preview(None, REFERENCE)
    assert result["exact_tokens"] is None and not result["predeclared_preview_check_passed"]


def test_changed_vision_action_requires_observation_reference_and_payload_change():
    action = {"type": "run_probe", "transforms": []}
    snapshot = {"actions": [
        {"id": "first", "status": "completed", "decision": {"action": action}},
        {"id": "second", "status": "completed", "decision": {"action": copy.deepcopy(action),
         "based_on_observation_ids": ["observed"], "decision_summary": "Scripted evaluator test"}}],
        "observations": [{"id": "observed", "action_id": "first", "result_type": "run_probe", "payload": {"executed": True}}]}
    assert HARNESS.changed_vision_edges(snapshot) == []
    snapshot["actions"][1]["decision"]["action"]["transforms"] = [{"type": "resize", "width": 800, "height": 600}]
    assert len(HARNESS.changed_vision_edges(snapshot)) == 1
    snapshot["actions"][1]["decision"]["based_on_observation_ids"] = []
    assert HARNESS.changed_vision_edges(snapshot) == []
