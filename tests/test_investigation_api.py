"""Investigation lifecycle/HTTP boundaries with an explicitly scripted async loop."""
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from filelock import FileLock, Timeout

from engine.api.investigation_routes import build_router
from engine.investigations.manager import InvestigationManager
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.service import WorkspaceService
from spec.investigation import InvestigationBudget, InvestigationTransport, NextAction, TaskState


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.service = WorkspaceService(tmp_path / "workspace")
        self.project = self.service.create_project("Investigation API software test", "custom")
        self.manager = InvestigationManager(self.service)
        app = FastAPI()
        app.include_router(build_router(self.manager))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.url = f"/projects/{self.project.id}/investigations"
        self.calls = 0
        self.entered = asyncio.Event()
        self.transports: list[InvestigationTransport] = []

    async def loop(self, _root: str, _project: str, _task: str, _url: str, _model: str, *,
                   transport: InvestigationTransport = "structured_json") -> TaskState:
        self.calls += 1
        self.transports.append(transport)
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("The scripted loop should be cancelled")

    async def start(self, **values: Any) -> httpx.Response:
        return await self.client.post(self.url, json={"runtime_version": "a0.1", "objective": "Read supplied labels",
                                                     "client_request_id": "request-1", **values})


@pytest.fixture
async def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    harness = Harness(tmp_path)
    monkeypatch.setattr("engine.investigations.manager.investigate", harness.loop)
    try:
        yield harness
    finally:
        await harness.manager.close()
        await harness.client.aclose()


async def test_start_is_prompt_idempotent_and_project_exclusive(api: Harness) -> None:
    root = api.service.root(api.project.id)
    annotations = (root / "annotations.json").read_bytes()
    response = await asyncio.wait_for(api.start(), .5)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state["schema_version"] == "a0.1" and state["status"] == "running"
    await asyncio.wait_for(api.entered.wait(), .5)
    duplicate = await api.start()
    assert duplicate.status_code == 200 and duplicate.json()["id"] == state["id"] and api.calls == 1
    assert (await api.start(objective="A changed objective")).status_code == 409
    assert (await api.start(budget={"max_actions": 3})).status_code == 409
    assert (await api.start(client_request_id="request-2")).status_code == 409
    listing = await api.client.get(api.url)
    detail = await api.client.get(api.url + "/" + state["id"])
    assert listing.json()[0]["id"] == state["id"]
    assert set(detail.json()) == {"state", "actions", "observations"}
    assert not detail.json()["actions"] and not detail.json()["observations"]
    assert not api.service.events(api.project.id)
    assert annotations == (root / "annotations.json").read_bytes()


async def test_duplicate_after_restart_returns_saved_task_without_execution(api: Harness) -> None:
    created = (await api.start()).json()
    await asyncio.wait_for(api.entered.wait(), 5)
    await api.manager.close()
    replacement = InvestigationManager(api.service)
    try:
        result = await replacement.start(api.project.id, "Read supplied labels", "request-1")
        assert result.id == created["id"] and result.status == "interrupted"
        assert not replacement.tasks and api.calls == 1
    finally:
        await replacement.close()


async def test_manager_passes_explicit_response_transport_from_saved_settings(api: Harness) -> None:
    settings = api.service.repository.settings()
    assert settings.investigation_transport == "structured_json"
    settings.investigation_transport = "decision_function"
    api.service.repository.save_settings(settings)
    await api.start()
    await asyncio.wait_for(api.entered.wait(), .5)
    assert api.transports == ["decision_function"]


async def test_pause_waits_for_teardown_preserves_budget_and_resumes(api: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup_started, allow_cleanup, cleanup_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def loop(root: str, project: str, task: str, url: str, model: str, *,
                   transport: InvestigationTransport = "structured_json") -> TaskState:
        try:
            return await api.loop(root, project, task, url, model, transport=transport)
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()
            cleanup_done.set()
    monkeypatch.setattr("engine.investigations.manager.investigate", loop)
    created = (await api.start()).json()
    await asyncio.wait_for(api.entered.wait(), 5)
    endpoint = api.url + "/" + created["id"]
    stale = await api.client.post(endpoint + "/control", json={"expected_revision": 10, "action": "pause"})
    assert stale.status_code == 409 and not cleanup_started.is_set()
    pausing = asyncio.create_task(api.client.post(endpoint + "/control", json={"expected_revision": 0, "action": "pause"}))
    await asyncio.wait_for(cleanup_started.wait(), .5)
    assert not pausing.done() and not cleanup_done.is_set()
    with pytest.raises(Timeout):
        FileLock(api.manager.store.root(api.project.id, created["id"]) / ".runner.lock", timeout=0).acquire()
    allow_cleanup.set()
    paused = (await pausing).json()
    assert cleanup_done.is_set() and paused["status"] == "paused" and paused["budget"]["elapsed_s"] > 0
    assert not api.manager.tasks
    api.entered.clear()
    resumed = await api.client.post(endpoint + "/resume", json={"expected_revision": paused["revision"]})
    assert resumed.status_code == 200 and resumed.json()["status"] == "running"
    assert resumed.json()["budget"]["elapsed_s"] >= paused["budget"]["elapsed_s"]
    await asyncio.wait_for(api.entered.wait(), 5)
    assert api.calls == 2
    state = api.manager.store.get(api.project.id, created["id"])
    cancelled = await api.client.post(endpoint + "/control", json={"expected_revision": state.revision, "action": "cancel"})
    assert cancelled.json()["status"] == "cancelled"
    assert (await api.client.post(endpoint + "/resume", json={"expected_revision": cancelled.json()["revision"]})).status_code == 409


async def test_close_waits_for_cleanup_and_releases_all_owned_leases(api: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    cleanup_started, cleanup_allowed = asyncio.Event(), asyncio.Event()
    async def loop(root: str, project: str, task: str, url: str, model: str, *,
                   transport: InvestigationTransport = "structured_json") -> TaskState:
        try:
            return await api.loop(root, project, task, url, model, transport=transport)
        finally:
            cleanup_started.set()
            await cleanup_allowed.wait()
    monkeypatch.setattr("engine.investigations.manager.investigate", loop)
    created = (await api.start()).json()
    await asyncio.wait_for(api.entered.wait(), 5)
    closing = asyncio.create_task(api.manager.close())
    await cleanup_started.wait()
    assert not closing.done()
    cleanup_allowed.set()
    await closing
    assert not api.manager.tasks
    assert api.manager.store.get(api.project.id, created["id"]).status == "interrupted"
    with FileLock(api.manager.store.root(api.project.id, created["id"]) / ".runner.lock", timeout=0):
        pass


async def test_cancel_before_runner_first_instruction_does_not_leak_lease(api: Harness) -> None:
    created = await api.manager.start(api.project.id, "Immediate stop", "immediate")
    cancelled = await api.manager.control(api.project.id, created.id, created.revision, "cancel")
    assert cancelled.status == "cancelled" and api.calls == 0 and not api.manager.tasks
    with FileLock(api.manager.store.root(api.project.id, created.id) / ".runner.lock", timeout=0):
        pass
    with FileLock(api.service.root(api.project.id) / "investigations/.runner.lock", timeout=0):
        pass


@pytest.mark.parametrize("pending", ["model", "action"])
async def test_get_never_recovers_or_executes_crashed_pending_attempt(api: Harness, monkeypatch: pytest.MonkeyPatch, pending: str) -> None:
    store = api.manager.store
    task = store.create(api.project.id, "Interrupted model request")
    call = store.start_model_call(api.project.id, task.id, {}, "scripted-test")
    if pending == "action":
        decision = NextAction.model_validate({"state_revision": task.revision,
            "decision_summary": "Scripted reservation test", "action": {"type": "inspect_media"}})
        store.finish_model_call(api.project.id, task.id, call.id, decision.model_dump(mode="json"))
        store.reserve_action(api.project.id, task.id, decision)
    state = store.get(api.project.id, task.id)
    path = store.root(api.project.id, task.id) / "task.json"
    before = path.read_bytes()
    snapshot = await api.client.get(api.url + "/" + task.id)
    assert snapshot.json()["state"]["pending_" + ("model_call" if pending == "model" else "action") + "_id"]
    assert path.read_bytes() == before and api.calls == 0
    async def resumed(root: str, project: str, identifier: str, _url: str, _model: str, *,
                      transport: InvestigationTransport = "structured_json") -> TaskState:
        recovered = InvestigationStore(WorkspaceService(Path(root)))
        state = recovered.get(project, identifier)
        assert state.pending_model_call_id is state.pending_action_id is None and state.budget.model_calls == 1
        if pending == "model":
            assert recovered.model_calls(project, identifier)[0].status == "interrupted"
        else:
            assert recovered.actions(project, identifier)[0].status == "interrupted"
            observation = recovered.observations(project, identifier)[0]
            assert observation.payload == {"effect_status": "unknown", "automatic_retry": False}
        api.entered.set()
        return recovered.stop(project, identifier, "Scripted observation: no automatic reexecution")
    monkeypatch.setattr("engine.investigations.manager.investigate", resumed)
    response = await api.client.post(api.url + "/" + task.id + "/resume", json={"expected_revision": state.revision})
    assert response.status_code == 200
    await asyncio.wait_for(api.entered.wait(), .5)
    await asyncio.sleep(0)
    assert store.get(api.project.id, task.id).status == "inconclusive"
    assert len(store.model_calls(api.project.id, task.id)) == 1


async def test_awaiting_input_resume_requires_answer_and_retains_call_budget(api: Harness) -> None:
    store = api.manager.store
    task = store.create(api.project.id, "Ask a user fact")
    call = store.start_model_call(api.project.id, task.id, {}, "scripted-test")
    decision = NextAction.model_validate({"state_revision": task.revision, "decision_summary": "Need a fact",
                                         "action": {"type": "ask_user", "question": "Which printed identifier matters?"}})
    store.finish_model_call(api.project.id, task.id, call.id, decision.model_dump(mode="json"))
    receipt = store.reserve_action(api.project.id, task.id, decision)
    store.complete_action(api.project.id, task.id, receipt.id, {"executed": False})
    state = store.get(api.project.id, task.id)
    endpoint = api.url + "/" + task.id + "/resume"
    rejected = await api.client.post(endpoint, json={"expected_revision": state.revision})
    assert rejected.status_code == 400 and not api.manager.tasks
    resumed = await api.client.post(endpoint, json={"expected_revision": state.revision, "answer": "The package identifier"})
    assert resumed.status_code == 200
    assert resumed.json()["user_answers"] == ["The package identifier"]
    assert resumed.json()["budget"]["model_calls"] == resumed.json()["budget"]["actions"] == 1
    await asyncio.wait_for(api.entered.wait(), 5)


async def test_second_manager_cannot_resume_or_control_an_owned_runner(api: Harness) -> None:
    created = (await api.start()).json()
    await asyncio.wait_for(api.entered.wait(), 5)
    other = InvestigationManager(api.service)
    try:
        with pytest.raises(InvestigationConflict, match="already owns"):
            await other.resume(api.project.id, created["id"], created["revision"])
        with pytest.raises(InvestigationConflict, match="already owns"):
            await other.control(api.project.id, created["id"], created["revision"], "cancel")
        assert api.manager.store.get(api.project.id, created["id"]).status == "running" and api.calls == 1
    finally:
        await other.close()


async def test_cumulative_remaining_time_is_used_after_resume(api: Harness) -> None:
    store = api.manager.store
    task = store.create(api.project.id, "Small remaining budget", InvestigationBudget(max_elapsed_s=1))
    store.stop(api.project.id, task.id, "Prior controlled pause", status="paused")
    with api.service.repository.lock:
        record = store._load(api.project.id, task.id)
        record.task.budget.elapsed_s = .95
        store._save(record)
    state = store.get(api.project.id, task.id)
    await api.manager.resume(api.project.id, task.id, state.revision)
    runner = api.manager.tasks[api.project.id, task.id]
    await asyncio.wait_for(asyncio.shield(runner), .5)
    final = store.get(api.project.id, task.id)
    assert final.status == "inconclusive" and "elapsed-time budget" in final.stop_reason
    assert final.budget.elapsed_s >= 1 and api.calls == 1


async def test_uncertain_creation_intent_prevents_duplicate_creation(api: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_create(*_args: Any, **_kwargs: Any) -> TaskState:
        raise OSError("Simulated process failure while creating task")
    monkeypatch.setattr(api.manager.store, "create", failed_create)
    with pytest.raises(OSError):
        await api.manager.start(api.project.id, "Uncertain creation", "creation-failure")
    with pytest.raises(InvestigationConflict, match="Creation was interrupted"):
        await api.manager.start(api.project.id, "Uncertain creation", "creation-failure")
    assert not api.manager.list(api.project.id) and not api.manager.tasks


@pytest.mark.parametrize("change", [{"runtime_version": "legacy"}, {"objective": ""}, {"client_request_id": ""},
                                    {"unexpected_path": "/tmp/anything"}])
async def test_start_request_is_strict_and_versioned(api: Harness, change: dict[str, Any]) -> None:
    assert (await api.start(**change)).status_code == 422
    assert not api.manager.list(api.project.id)


async def test_unknown_project_task_and_wrong_owner_are_not_found(api: Harness) -> None:
    assert (await api.client.get("/projects/nonexistent/investigations")).status_code == 404
    assert (await api.client.get(api.url + "/" + "0" * 32)).status_code == 404
    another = api.service.create_project("Other project")
    task = api.manager.store.create(another.id, "Private task")
    assert (await api.client.get(api.url + "/" + task.id)).status_code == 404
