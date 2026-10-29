from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, plan_from_context
from agent.task_validation import validate_output_behavior, validate_spatial_intent
from engine.api import create_app
from engine.compiler import compile_pipeline
from engine.runtime import run_pipeline
from engine.service import WorkspaceService
from engine.zones import read_zone_state, save_zone_state
from spec.models import Zone


def spatial_decision() -> PlanDecision:
    return PlanDecision(message="Count pallets in B.", choices=[PatternChoice(
        use_case="custom", objects=["pallet"], use_zones=True, zone_ids=["B"],
        count_threshold=None, metric="count_mae", target=.5)])


def test_count_only_intent_does_not_acquire_regions_events_or_recall_metric() -> None:
    decision = spatial_decision()
    with pytest.raises(ValueError, match="spatial region|whole-image"):
        validate_spatial_intent(decision, "Count pallets across each image")
    decision.choices[0].count_threshold = 1
    with pytest.raises(ValueError, match="event trigger"):
        validate_output_behavior(decision, "Count pallets per lane. No alerts.")
    decision.choices[0].count_threshold = None
    decision.choices[0].metric = "recall"
    with pytest.raises(ValueError, match="counting task"):
        validate_output_behavior(decision, "Count pallets per lane.")
    validate_output_behavior(decision, "Count pallets. Evaluate recall target 0.8.")


def test_real_project_has_no_invented_lanes_and_requests_actual_geometry(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("My app", "custom")
    state = read_zone_state(service.root(project.id))
    assert state.zones == [] and not state.confirmed
    result = plan_from_context(spatial_decision(), "Count pallets in lane B", "media", "fixture-color-v1",
                               {"zones_confirmed": False, "saved_zone_ids": []})
    assert result.needs_zones and result.questions and not result.candidates
    assert "B" in result.questions[0]


def test_human_zone_save_is_bound_to_actual_coordinates_and_legacy_is_unconfirmed(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    project = client.post("/projects", json={"name": "Spatial app", "use_case": "custom"}).json()
    url = f"/projects/{project['id']}/zones"
    assert client.get(url).json() == {"zones": [], "confirmed": False, "origin": "unconfirmed"}
    polygon = {"zones": [{"id": "B", "polygon": [[0, 0], [.5, 0], [.5, 1], [0, 1]]}]}
    saved = client.put(url, json=polygon)
    assert saved.status_code == 200 and saved.json()["confirmed"] and saved.json()["origin"] == "user"
    root = WorkspaceService(tmp_path).root(project["id"])
    path = root / "zones/lanes.json"
    path.write_text(path.read_text().replace('"B"', '"C"'))
    assert not read_zone_state(root).confirmed
    (root / "zones/confirmation.json").unlink()
    assert read_zone_state(root).zones and not read_zone_state(root).confirmed
    invalid = {"zones": [{"id": "bad", "polygon": [[0, 0], [0, 0], [0, 0]]}]}
    assert client.put(url, json=invalid).status_code == 400


def test_custom_spatial_count_runs_only_in_requested_saved_region(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Explicit synthetic spatial test", "custom")
    service.demo(project.id)
    root = service.root(project.id)
    result = plan_from_context(spatial_decision(), "Count pallets in lane B", "media", "fixture-color-v1",
                               {"zones_confirmed": True, "saved_zone_ids": ["A", "B", "C", "D"]})
    assert not result.needs_zones
    run = run_pipeline(result.candidates[0], root, max_frames=3)
    assert run.frames and any(frame.detections for frame in run.frames)
    assert all(det.zone == "B" for frame in run.frames for det in frame.detections)
    assert all(set(frame.counts) <= {"B"} and not frame.events for frame in run.frames)
    missing = result.candidates[0].model_copy(deep=True)
    next(block for block in missing.blocks if block.type == "zone_filter").params["include_ids"] = ["absent"]
    with pytest.raises(ValueError, match="requested regions"):
        compile_pipeline(missing, root)


def test_unconfirmed_real_geometry_cannot_compile_as_known_warehouse_layout(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Legacy real geometry", "custom")
    root = service.root(project.id)
    zones = [Zone(id="B", polygon=[(0, 0), (1, 0), (1, 1), (0, 1)])]
    save_zone_state(root, zones)
    (root / "zones/confirmation.json").unlink()
    spec = compile_decision(spatial_decision(), "media", "fixture-color-v1").candidates[0]
    with pytest.raises(ValueError, match="unconfirmed"):
        compile_pipeline(spec, root)


def test_plain_reading_needs_no_invented_sku_but_comparison_requires_value() -> None:
    decision = PlanDecision(message="Read codes.", choices=[PatternChoice(use_case="custom",
        pipeline_type="barcode", metric="text_accuracy", target=.95)])
    reading = plan_from_context(decision, "Read these package barcodes and show their codes", "media", "fixture-color-v1")
    assert {block.type for block in reading.candidates[0].blocks} == {"frame_sample", "barcode"}
    checking = plan_from_context(decision, "Check these package barcodes", "media", "fixture-color-v1")
    assert checking.questions and not checking.candidates and not checking.needs_zones


def test_spatial_intent_cannot_silently_become_whole_image_counts() -> None:
    decision = PlanDecision(message="Count.", choices=[PatternChoice(use_case="custom", objects=["pallet"],
        metric="count_mae", target=.5)])
    with pytest.raises(ValueError, match="spatial counts"):
        validate_spatial_intent(decision, "Count pallets in each lane")
    validate_spatial_intent(spatial_decision(), "Count pallets in lane B")
    result = compile_decision(decision, "media", "fixture-color-v1")
    assert not any(block.type in {"rule", "sink_event"} for block in result.candidates[0].blocks)
