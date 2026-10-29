"""Initial-goal region provenance and read-only graph semantics."""
import json
from pathlib import Path

import pytest

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, plan_from_context
from engine.blocks.spatial import load_zones
from engine.runtime import run_pipeline
from engine.runtime.fixtures import generate_demo
from engine.zones import read_zone_state, save_zone_state
from spec.models import Zone


def test_modified_geometry_cannot_fall_back_to_legacy_fixture_confirmation(tmp_path: Path) -> None:
    generate_demo(tmp_path)
    legacy = read_zone_state(tmp_path)
    assert legacy.confirmed and legacy.origin == "fixture"
    save_zone_state(tmp_path, legacy.zones, origin="fixture")
    path = tmp_path / "zones/lanes.json"
    geometry = json.loads(path.read_text())
    geometry["zones"][0]["polygon"][1][0] = .2
    path.write_text(json.dumps(geometry))
    state = read_zone_state(tmp_path)
    assert state.zones and not state.confirmed and state.origin == "unconfirmed"
    with pytest.raises(ValueError, match="unconfirmed"):
        load_zones("zones/lanes.json", tmp_path)


def test_receipt_reconfirmation_binds_current_user_geometry(tmp_path: Path) -> None:
    zone = Zone(id="Loading", polygon=[(0, 0), (1, 0), (1, 1), (0, 1)])
    assert not read_zone_state(tmp_path).confirmed
    saved = save_zone_state(tmp_path, [zone])
    assert saved == read_zone_state(tmp_path) and saved.origin == "user"


@pytest.mark.parametrize("reader", ["ocr", "barcode"])
def test_custom_read_only_goal_never_invents_expected_text_or_sink(reader: str) -> None:
    choice = PatternChoice.model_validate({"use_case": "custom", "pipeline_type": reader,
                                          "metric": "text_accuracy", "target": .9})
    result = compile_decision(PlanDecision(message="Read only", choices=[choice]), "media", "fixture-color-v1")
    assert [block.type for block in result.candidates[0].blocks] == ["frame_sample", reader]
    missing = plan_from_context(PlanDecision(message="Read", choices=[choice]),
                               "Read and compare against the expected package code", "media", "fixture-color-v1")
    assert missing.questions and not missing.candidates


def test_plain_count_outputs_global_count_without_regions_or_events(tmp_path: Path) -> None:
    generate_demo(tmp_path)
    choice = PatternChoice(use_case="custom", objects=["pallet"], metric="count_mae", target=.5)
    candidate = compile_decision(PlanDecision(message="Count", choices=[choice]), "media", "fixture-color-v1").candidates[0]
    assert not {"zone_filter", "rule", "sink_event"} & {block.type for block in candidate.blocks}
    preview = run_pipeline(candidate, tmp_path, max_frames=2)
    assert preview.frames and all(frame.counts == {"all": len(frame.detections)} for frame in preview.frames)
    assert all(not frame.events for frame in preview.frames)


async def test_benchmark_unknown_case_never_returns_vacuous_success(tmp_path: Path) -> None:
    from evals.run_custom_goals import run
    with pytest.raises(ValueError, match="Unknown benchmark"):
        await run(tmp_path / "workspace", tmp_path / "report.json", "unused", "unused", ["typo-case"])
    assert not (tmp_path / "workspace").exists() and not (tmp_path / "report.json").exists()
