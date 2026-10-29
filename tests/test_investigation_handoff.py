"""Actual fixture execution tests the handoff protocol, not learned-model quality."""
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_investigation_workflows import Harness

from agent.machine import AgentConflict
from engine.api.application import create_app
from engine.builds.store import BuildStore
from engine.investigations.handoff import ReviewHandoff
from engine.investigations.store import InvestigationConflict
from engine.runtime import run_pipeline
from spec.handoff import AbortHandoff, AcceptHandoff, PrepareHandoff
from spec.investigation import Finish


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = Harness(tmp_path, monkeypatch)
    dataset = harness.service.annotations(harness.project_id)
    for annotation in dataset.annotations:
        annotation.reviewed = False
    harness.service.save_annotations(harness.project_id, dataset)
    harness.inspect()
    observation = harness.construct()
    assert observation.status == "completed", observation.error
    action = Finish(type="finish", outcome="draft_ready", summary="Scripted protocol fixture only",
        workflow_revision_id=observation.payload["workflow_revision_id"], evidence_ids=[observation.id])
    receipt = harness.reserve(action)
    harness.store.complete_action(harness.project_id, harness.task_id, receipt.id, {})
    return harness


def selection(harness: Harness) -> PrepareHandoff:
    state = harness.store.get(harness.project_id, harness.task_id)
    return PrepareHandoff(expected_revision=state.revision, workflow_revision_id=state.selected_workflow_revision,
                           preview_observation_id=state.preview_observation_id)


def prepare(harness: Harness) -> tuple[ReviewHandoff, AcceptHandoff]:
    handoff = ReviewHandoff(harness.service)
    proposal = handoff.prepare(harness.project_id, harness.task_id, selection(harness))
    return handoff, AcceptHandoff(proposal_id=proposal.id, proposal_hash=proposal.proposal_hash,
                                  client_request_id="human-import-test", acknowledge_source_rebind=True)


def test_actual_handoff_preserves_graph_models_and_review_gates(ready: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff, request = prepare(ready)
    old = handoff._proposal(ready.project_id, handoff._read(ready.project_id))
    before = {path: path.read_bytes() for path in [ready.root / "annotations.json",
        ready.store.root(ready.project_id, ready.task_id) / "task.json"]}
    calls: list[Any] = []

    def actual(spec: Any, root: Path, **kwargs: Any) -> Any:
        calls.append(spec)
        return run_pipeline(spec, root, **kwargs)

    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", actual)
    result = handoff.accept(ready.project_id, ready.task_id, request)
    assert len(calls) == 1
    assert result.build.status == "awaiting_review" and result.build.next_action == "configure_evaluation"
    assert result.build.investigation_origin == result.receipt
    project = ready.service.get_project(ready.project_id)
    assert project.candidates == [old.candidate] and project.candidates[0].inputs["source"].path == "media"
    assert result.build.preview and len(result.build.preview.frames) == 5
    assert all(str(ready.root / "media") in frame.image_path for frame in result.build.preview.frames)
    assert result.build.plan and result.build.plan.model_selections == old.bindings
    assert result.build.plan.planning_options_artifact_id
    assert not result.build.tool_events and not result.build.evaluations
    assert not project.evaluations and not project.deployment_id and project.fixture and project.synthetic
    assert before == {path: path.read_bytes() for path in before}
    assert not ready.service.events(ready.project_id)
    assert not any(row.reviewed for row in ready.service.annotations(ready.project_id).annotations)
    with pytest.raises(ValueError):
        ready.service.run(ready.project_id)
    again = handoff.accept(ready.project_id, ready.task_id, request)
    assert again.receipt == result.receipt and again.build.id == result.build.id and len(calls) == 1
    assert handoff.status(ready.project_id, ready.task_id).build.id == result.build.id


@pytest.mark.parametrize("changed", ["media", "annotations", "project"])
def test_stale_proposal_rejects_before_preview(ready: Harness, monkeypatch: pytest.MonkeyPatch, changed: str) -> None:
    handoff, request = prepare(ready)
    if changed == "media":
        path = Path(ready.service.get_project(ready.project_id).media[0])
        path.write_bytes(path.read_bytes() + b"changed")
    elif changed == "annotations":
        path = ready.root / "annotations.json"
        value = json.loads(path.read_text())
        value["annotations"][0]["reviewed"] = not value["annotations"][0]["reviewed"]
        path.write_text(json.dumps(value))
    else:
        project = ready.service.get_project(ready.project_id)
        project.name = "Changed by the user"
        ready.service.repository.save(project)
    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", lambda *_a, **_k: pytest.fail("Stale inference"))
    with pytest.raises(ValueError, match="changed|Changed"):
        handoff.accept(ready.project_id, ready.task_id, request)
    assert not ready.service.get_project(ready.project_id).candidates


def test_interrupted_preview_never_repeats_and_requires_explicit_new_proposal(ready: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff, request = prepare(ready)
    calls = 0

    def crash(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise KeyboardInterrupt("simulate process death")

    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", crash)
    with pytest.raises(KeyboardInterrupt):
        handoff.accept(ready.project_id, ready.task_id, request)
    with pytest.raises(AgentConflict, match="handoff"):
        BuildStore(ready.service).create(ready.project_id, "Cannot race unfinished handoff")
    assert handoff.status(ready.project_id, ready.task_id).status == "interrupted"
    with pytest.raises(InvestigationConflict, match="not repeat automatically"):
        handoff.accept(ready.project_id, ready.task_id, request)
    assert calls == 1 and not ready.service.get_project(ready.project_id).candidates
    fresh = handoff.prepare(ready.project_id, ready.task_id, selection(ready))
    assert fresh.id != request.proposal_id


def test_inconclusive_saved_preview_can_be_explicitly_recovered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(tmp_path, monkeypatch)
    harness.inspect()
    harness.construct()
    harness.store.stop(harness.project_id, harness.task_id, "Final citation did not match the selected preview")
    before = (harness.store.root(harness.project_id, harness.task_id) / "task.json").read_bytes()
    handoff, request = prepare(harness)
    proposal = handoff.status(harness.project_id, harness.task_id).proposal
    assert proposal.origin_task_status == "inconclusive"
    assert "did not complete" in proposal.limitations[0]
    result = handoff.accept(harness.project_id, harness.task_id, request)
    assert result.receipt.origin_task_status == "inconclusive"
    assert result.receipt.origin_stop_reason == "Final citation did not match the selected preview"
    assert before == (harness.store.root(harness.project_id, harness.task_id) / "task.json").read_bytes()


def test_http_handoff_returns_durable_build_origin(ready: Harness) -> None:
    app = create_app(ready.service.repository.root)
    client = TestClient(app)
    path = f"/projects/{ready.project_id}/investigations/{ready.task_id}/handoff"
    response = client.post(path + "/prepare", json=selection(ready).model_dump(mode="json"))
    assert response.status_code == 200, response.text
    proposal = response.json()
    response = client.post(path + "/accept", json={"proposal_id": proposal["id"], "proposal_hash": proposal["proposal_hash"],
        "client_request_id": "native-network-key", "acknowledge_source_rebind": True})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["build"]["investigation_origin"] == payload["receipt"]
    assert client.get(path).json()["receipt"] == payload["receipt"]
    assert client.get(f"/projects/{ready.project_id}/build").json()["investigation_origin"] == payload["receipt"]
    capture = ready.service.repository.root.parent / "handoff-wire"
    capture.mkdir()
    (capture / "proposal.json").write_text(json.dumps(proposal, indent=2))
    (capture / "result.json").write_text(json.dumps(payload, indent=2))
    (capture / "status.json").write_text(json.dumps(client.get(path).json(), indent=2))
    print(f"Actual backend wire fixtures: {capture}")


@pytest.mark.parametrize("point", ["project", "build", "plan", "execution", "receipt", "completed"])
def test_commit_process_death_recovers_same_build_without_inference(ready: Harness, monkeypatch: pytest.MonkeyPatch, point: str) -> None:
    from engine.store.repository import atomic_model

    handoff, request = prepare(ready)
    crashed = False

    def interrupted(path: Path, value: Any) -> None:
        nonlocal crashed
        atomic_model(path, value)
        matches = {"project": path.name == "project.json", "build": path.name == "build.json",
                   "plan": path.parent.name == "plans", "execution": path.parent.name == "executions",
                   "receipt": path.name.endswith(".receipt.json"),
                   "completed": path.name == "review-handoff.json" and value.status == "completed"}
        if not crashed and matches[point]:
            crashed = True
            raise KeyboardInterrupt("Process died after durable " + point)

    for module in ["engine.investigations.handoff", "engine.builds.store", "engine.platform.store"]:
        monkeypatch.setattr(module + ".atomic_model", interrupted)
    with pytest.raises(KeyboardInterrupt):
        handoff.accept(ready.project_id, ready.task_id, request)
    assert crashed
    journal = handoff._read(ready.project_id)
    identifier = journal.receipt.build_id
    if point != "completed":
        before_labels = (ready.root / "annotations.json").read_bytes()
        with pytest.raises(AgentConflict, match="Recover"):
            ready.service.save_annotations(ready.project_id, ready.service.annotations(ready.project_id))
        assert (ready.root / "annotations.json").read_bytes() == before_labels
        client = TestClient(create_app(ready.service.repository.root))
        assert client.put(f"/projects/{ready.project_id}/zones", json={"zones": []}).status_code == 409
    settings = ready.service.repository.settings()
    settings.planner_model = "Unrelated planner setting does not change saved CV model bindings"
    ready.service.repository.save_settings(settings)
    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", lambda *_a, **_k: pytest.fail("Recovery repeated inference"))
    result = handoff.status(ready.project_id, ready.task_id)
    assert result.status == "completed" and result.build.id == identifier
    assert result.build.execution and result.build.execution.status == "paused"
    assert len(BuildStore(ready.service).platform.plans(ready.project_id, identifier)) == 1
    assert len(ready.service.get_project(ready.project_id).candidates) == 1
    assert handoff.accept(ready.project_id, ready.task_id, request).receipt == result.receipt


def test_modified_artifact_cannot_be_imported(ready: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff, request = prepare(ready)
    state = ready.store.get(ready.project_id, ready.task_id)
    observation = ready.store.get_observation(ready.project_id, ready.task_id, state.preview_observation_id)
    artifact = ready.store.root(ready.project_id, ready.task_id) / "artifacts" / observation.payload["revision_artifact"]["artifact_id"]
    artifact.write_text(artifact.read_text() + " ")
    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", lambda *_a, **_k: pytest.fail("Tampered inference"))
    with pytest.raises(ValueError, match="artifact content changed"):
        handoff.accept(ready.project_id, ready.task_id, request)
    assert not ready.service.get_project(ready.project_id).candidates


def test_project_edit_during_preview_is_not_overwritten(ready: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    handoff, request = prepare(ready)

    def actual(spec: Any, root: Path, **kwargs: Any) -> Any:
        result = run_pipeline(spec, root, **kwargs)
        project = ready.service.get_project(ready.project_id)
        project.name = "User edit made while previewing"
        ready.service.repository.save(project)
        return result

    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", actual)
    with pytest.raises(InvestigationConflict, match="Project changed"):
        handoff.accept(ready.project_id, ready.task_id, request)
    assert ready.service.get_project(ready.project_id).name == "User edit made while previewing"
    assert not ready.service.get_project(ready.project_id).candidates
    assert handoff.status(ready.project_id, ready.task_id).status == "interrupted"


@pytest.mark.parametrize("foreign_project_edit", [False, True])
def test_external_drift_after_commit_crash_has_explicit_safe_discard(ready: Harness, monkeypatch: pytest.MonkeyPatch, foreign_project_edit: bool) -> None:
    from engine.store.repository import atomic_model
    handoff, request = prepare(ready)
    project_before = ready.service.get_project(ready.project_id)
    original_adopt = handoff.builds.adopt_investigation
    monkeypatch.setattr(handoff.builds, "adopt_investigation", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt("after project commit")))
    with pytest.raises(KeyboardInterrupt):
        handoff.accept(ready.project_id, ready.task_id, request)
    monkeypatch.setattr(handoff.builds, "adopt_investigation", original_adopt)
    # External file drift is outside API locks. Preserve it even when discarding our partial app.
    image = Path(project_before.media[0])
    image.write_bytes(image.read_bytes() + b"externally changed")
    if foreign_project_edit:
        project = ready.service.get_project(ready.project_id)
        project.name = "External project edit must survive"
        atomic_model(ready.root / "project.json", project)
    status = handoff.status(ready.project_id, ready.task_id)
    assert status.status == "conflict" and status.can_abort
    discard = AbortHandoff(proposal_id=request.proposal_id, proposal_hash=request.proposal_hash, acknowledge_discard=True)
    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", lambda *_a, **_k: pytest.fail("Discard repeated inference"))
    if foreign_project_edit:
        with pytest.raises(InvestigationConflict, match="cannot overwrite"):
            handoff.abort(ready.project_id, ready.task_id, discard)
        assert ready.service.get_project(ready.project_id).name == "External project edit must survive"
    else:
        assert handoff.abort(ready.project_id, ready.task_id, discard).status == "interrupted"
        assert ready.service.get_project(ready.project_id) == project_before
        assert handoff.abort(ready.project_id, ready.task_id, discard).status == "interrupted"
    assert image.read_bytes().endswith(b"externally changed")


def test_handoff_preview_excludes_reserved_acceptance_and_preserves_exposure(ready: Harness) -> None:
    from engine.eval.protocol import read_configuration, save_configuration
    from engine.eval.usage import read_usage
    from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment
    config = read_configuration(ready.root, ready.service.annotations(ready.project_id))
    row = next(row for row in config.images if row.image_path.endswith("synthetic-03.png"))
    saved_config = save_configuration(ready.root, ready.service.annotations(ready.project_id), EvaluationConfigurationUpdate(
        expected_revision=config.revision, assignments=[EvidenceAssignment(image_path=row.image_path,
            split="acceptance", scene_group="reserved", data_origin=row.data_origin)], policy=config.policy))
    before = read_usage(ready.root)
    handoff, request = prepare(ready)
    result = handoff.accept(ready.project_id, ready.task_id, request)
    assert all(not frame.image_path.endswith("synthetic-03.png") for frame in result.build.preview.frames)
    after = read_usage(ready.root)
    assert all(item in after.uses for item in before.uses)
    assert read_configuration(ready.root, ready.service.annotations(ready.project_id)).revision == saved_config.revision


def test_imported_plan_bindings_survive_guarded_refinement(ready: Harness) -> None:
    from agent.machine import Phase
    from engine.builds.refinement import refine_app
    from spec.refinement import RefinementPatch
    handoff, request = prepare(ready)
    result = handoff.accept(ready.project_id, ready.task_id, request)
    platform = handoff.builds.platform
    before = ready.service.get_project(ready.project_id).candidates
    from copy import deepcopy

    from engine.builds.refinement_edits import apply_edit
    edited = deepcopy(before)
    patch = RefinementPatch(kind="confidence", confidence=.6)
    apply_edit(edited[0], patch, {})
    options, bindings = platform.inherited_bindings(ready.project_id, edited, Phase.PLAN, platform.plans(ready.project_id))
    assert options and result.build.plan and bindings == result.build.plan.model_selections
    changed = refine_app(ready.service, ready.project_id, patch)
    assert changed.preview.frames and ready.service.get_project(ready.project_id).candidates == edited
    assert result.receipt == handoff.status(ready.project_id, ready.task_id).receipt


def test_concurrent_accept_does_not_duplicate_preview(ready: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from filelock import Timeout
    handoff, request = prepare(ready)
    entered, release = Event(), Event()
    calls = 0
    def preview(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(10)
        return run_pipeline(*args, **kwargs)
    monkeypatch.setattr("engine.investigations.handoff.run_pipeline", preview)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(handoff.accept, ready.project_id, ready.task_id, request)
        assert entered.wait(10)
        try:
            with pytest.raises(Timeout):
                handoff.accept(ready.project_id, ready.task_id, request)
            assert handoff.status(ready.project_id, ready.task_id).status == "committing"
        finally:
            release.set()
        assert first.result(timeout=30).build.status == "awaiting_review"
    assert calls == 1
