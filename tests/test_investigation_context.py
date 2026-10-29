"""Bootstrap input metadata must be current, bounded and free of inference effects."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from engine.investigations.store import InvestigationStore
from engine.service import WorkspaceService
from mcp_server.investigations import investigation_context
from spec.investigation import NextAction


def test_bootstrap_supplies_real_media_ids_and_hashes_without_exposure(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Bootstrap software test", "custom")
    source = tmp_path / "image.png"
    Image.new("RGB", (70, 40), "white").save(source)
    service.import_media(project.id, [str(source)])
    store = InvestigationStore(service)
    task = store.create(project.id, "Inspect the supplied image")
    owned = Path(service.get_project(project.id).media[0])
    context = investigation_context(store, project.id, task.id)
    summary = context["development_media"]
    row = summary["items"][0]
    assert row["media_id"].startswith("media-")
    assert row["source_sha256"] == hashlib.sha256(owned.read_bytes()).hexdigest()
    assert (row["width"], row["height"]) == (70, 40)
    assert row["membership"] == "development"
    assert summary["pixels_visible_to_planner"] is False
    assert not store.actions(project.id, task.id) and not store.observations(project.id, task.id)
    assert not (service.root(project.id) / "evaluation/usage.json").exists()
    owned.write_bytes(b"corrupted image")
    again = investigation_context(store, project.id, task.id)["development_media"]
    assert again["items"] == []
    assert again["unavailable"][0]["media_id"] == row["media_id"]
    assert not (service.root(project.id) / "evaluation/usage.json").exists()


@pytest.mark.parametrize("changed", [False, True])
def test_repeated_metadata_keeps_latest_context_and_complete_durable_history(tmp_path: Path, changed: bool) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Repeated metadata software test", "custom")
    store = InvestigationStore(service)
    task = store.create(project.id, "Choose an experiment")
    observations = []
    for index in range(3):
        state = store.get(project.id, task.id)
        decision = NextAction(state_revision=state.revision, decision_summary="Scripted metadata inspection",
                              action={"type": "inspect_capability", "capability_id": "model.example"})
        call = store.start_model_call(project.id, task.id, {}, "scripted-context-test")
        store.finish_model_call(project.id, task.id, call.id, {"decision": decision.model_dump(mode="json")})
        receipt = store.reserve_action(project.id, task.id, decision)
        digest = "c" * 64 if changed and index == 2 else "b" * 64
        observations.append(store.complete_action(project.id, task.id, receipt.id, {
            "model_view": {"id": "model.example", "descriptor_hash": digest, "probe_eligible": True}}))
    context = investigation_context(store, project.id, task.id)
    assert len(context["observations"]) == (2 if changed else 1)
    assert context["visible_observation_ids"][-1] == observations[-1].id
    assert len(context["inspected_capabilities"]) == 1
    assert context["inspected_capabilities"][0]["descriptor_hash"] == ("c" if changed else "b") * 64
    assert len(store.observations(project.id, task.id)) == 3
    assert {row["id"] for row in context["earlier_observations"]}.isdisjoint(context["visible_observation_ids"])
