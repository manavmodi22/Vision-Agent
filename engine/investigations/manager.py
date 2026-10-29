"""Owned background investigation runners and durable human control boundaries."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import Field

from agent.investigation import investigate
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.models.artifacts import canonical_hash
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.investigation import ActionReceipt, InvestigationBudget, Observation, TaskState
from spec.models import Contract


class InvestigationSnapshot(Contract):
    state: TaskState
    actions: list[ActionReceipt]
    observations: list[Observation]


class CreationReceipt(Contract):
    request_hash: str
    task_id: str | None = None


class CreationIndex(Contract):
    requests: dict[str, CreationReceipt] = Field(default_factory=dict)


@dataclass
class RunnerLease:
    project: FileLock
    task: FileLock

    def release(self) -> None:
        self.task.release()
        self.project.release()


class InvestigationManager:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.store = InvestigationStore(service)
        self.tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._closed = False

    def _folder(self, project_id: str) -> Path:
        return self.service.root(project_id) / "investigations"

    def _lifecycle(self, project_id: str) -> FileLock:
        folder = self._folder(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        return FileLock(folder / ".lifecycle.lock", timeout=0, thread_local=False)

    def list(self, project_id: str) -> list[TaskState]:
        with self.service.repository.lock:
            folder = self._folder(project_id)
            return sorted((self.store.get(project_id, path.parent.name)
                           for path in folder.glob("*/task.json")), key=lambda task: task.created_at, reverse=True)

    def snapshot(self, project_id: str, task_id: str) -> InvestigationSnapshot:
        with self.service.repository.lock:
            return InvestigationSnapshot(state=self.store.get(project_id, task_id),
                actions=self.store.actions(project_id, task_id), observations=self.store.observations(project_id, task_id))

    def _available(self, project_id: str, current_task: str | None = None) -> None:
        if self._closed:
            raise InvestigationConflict("The investigation manager is shutting down")
        if any(task.id != current_task and task.status in {"running", "awaiting_input", "paused", "interrupted"}
               for task in self.list(project_id)):
            raise InvestigationConflict("This project already has an active investigation; finish or cancel it first")

    def _lease(self, project_id: str, task_id: str) -> RunnerLease:
        project = FileLock(self._folder(project_id) / ".runner.lock", timeout=0, thread_local=False)
        task = FileLock(self.store.root(project_id, task_id) / ".runner.lock", timeout=0, thread_local=False)
        try:
            project.acquire()
            try:
                task.acquire()
            except BaseException:
                project.release()
                raise
        except Timeout as error:
            raise InvestigationConflict("An investigation runner already owns this project or task") from error
        return RunnerLease(project, task)

    def _spawn(self, project_id: str, task_id: str, lease: RunnerLease) -> None:
        try:
            task = asyncio.create_task(self._run(project_id, task_id, lease), name="investigation-" + task_id[:8])
            self.tasks[project_id, task_id] = task
            def finalized(completed: asyncio.Task[None]) -> None:
                # Cancellation before the coroutine's first instruction never
                # enters its finally block. Release that reserved lease as well.
                if self.tasks.get((project_id, task_id)) is completed:
                    self.tasks.pop((project_id, task_id), None)
                    try:
                        if self.store.get(project_id, task_id).status == "running":
                            self.store.stop(project_id, task_id, "Runner interrupted before startup", status="interrupted")
                    finally:
                        lease.release()
            task.add_done_callback(finalized)
        except BaseException:
            lease.release()
            raise

    async def start(self, project_id: str, objective: str, client_request_id: str,
                    budget: InvestigationBudget | None = None) -> TaskState:
        if not objective.strip() or len(objective) > 8000:
            raise ValueError("Describe an investigation in 1–8,000 characters")
        if not client_request_id.strip() or len(client_request_id) > 128:
            raise ValueError("A stable client request identifier of 1–128 characters is required")
        allowance = (budget or InvestigationBudget()).model_copy(deep=True)
        if allowance.model_calls or allowance.actions or allowance.probes or allowance.elapsed_s:
            raise ValueError("A new investigation cannot contain consumed budget counters")
        request_hash = canonical_hash({"runtime_version": "a0.1", "objective": objective,
                                       "budget": allowance.model_dump(mode="json")})
        key = hashlib.sha256(client_request_id.encode()).hexdigest()
        with self._lifecycle(project_id), self.service.repository.lock:
            index_path = self._folder(project_id) / "requests.json"
            index = CreationIndex.model_validate_json(index_path.read_text()) if index_path.exists() else CreationIndex()
            old = index.requests.get(key)
            if old is not None:
                if old.request_hash != request_hash:
                    raise InvestigationConflict("This client request identifier was already used with different objective or budget")
                if old.task_id is None:
                    raise InvestigationConflict("Creation was interrupted; inspect the project investigations before retrying")
                return self.store.get(project_id, old.task_id)  # A retry never starts a second runner.
            self._available(project_id)
            if len(index.requests) >= 10000:
                raise InvestigationConflict("This project has reached its investigation request limit")
            # A durable intent precedes creation. A crash in the two-document
            # transaction leaves an explicit uncertain request, never a duplicate.
            index.requests[key] = CreationReceipt(request_hash=request_hash)
            atomic_model(index_path, index)
            task = self.store.create(project_id, objective, allowance)
            index.requests[key].task_id = task.id
            atomic_model(index_path, index)
            try:
                lease = self._lease(project_id, task.id)
            except InvestigationConflict:
                self.store.stop(project_id, task.id, "Runner ownership unavailable; explicit resume is required", status="interrupted")
                raise
            self._spawn(project_id, task.id, lease)
            return task

    async def resume(self, project_id: str, task_id: str, expected_revision: int,
                     answer: str | None = None) -> TaskState:
        with self._lifecycle(project_id), self.service.repository.lock:
            state = self.store.get(project_id, task_id)
            self._revision(state, expected_revision)
            self._available(project_id, task_id)
            if (project_id, task_id) in self.tasks:
                raise InvestigationConflict("This investigation already has an active runner")
            lease = self._lease(project_id, task_id)
            try:
                # A free lease on a persisted running task proves only that no
                # host owns it now. Reconcile unknown attempts, never dispatch them.
                if state.status == "running" or state.pending_action_id or state.pending_model_call_id:
                    self.store.recover_pending(project_id, task_id)
                    state = self.store.stop(project_id, task_id,
                        "Previous runner stopped; interrupted attempts will not be repeated", status="interrupted")
                if state.budget.elapsed_s >= state.budget.max_elapsed_s:
                    lease.release()
                    return self.store.stop(project_id, task_id, "Cumulative investigation elapsed-time budget exhausted")
                state = self.store.resume(project_id, task_id, answer)
                self._spawn(project_id, task_id, lease)
                return state
            except BaseException:
                lease.release()
                raise

    @staticmethod
    def _revision(state: TaskState, expected: int) -> None:
        if state.revision != expected:
            raise InvestigationConflict("Investigation revision changed; reload before applying this control")

    async def _cancel_owned(self, project_id: str, task_id: str) -> bool:
        task = self.tasks.get((project_id, task_id))
        if task is None:
            return False
        if not task.done() and not task.cancelling():
            task.cancel()
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                # Request cancellation must not cancel teardown a second time.
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.shield(task)
                raise
        return True

    async def control(self, project_id: str, task_id: str, expected_revision: int,
                      action: Literal["pause", "cancel"]) -> TaskState:
        if action not in {"pause", "cancel"}:
            raise ValueError("Unknown investigation control")
        with self._lifecycle(project_id):
            with self.service.repository.lock:
                state = self.store.get(project_id, task_id)
                self._revision(state, expected_revision)
                if state.status not in {"running", "awaiting_input", "paused", "interrupted"}:
                    raise InvestigationConflict("This investigation is already terminal")
            if not await self._cancel_owned(project_id, task_id):
                lease = self._lease(project_id, task_id)
                try:
                    self.store.recover_pending(project_id, task_id)
                finally:
                    lease.release()
            return self.store.stop(project_id, task_id, "Paused by the user" if action == "pause" else "Cancelled by the user",
                                   status="paused" if action == "pause" else "cancelled")

    async def _run(self, project_id: str, task_id: str, lease: RunnerLease) -> None:
        started = time.monotonic()
        initial_elapsed = self.store.get(project_id, task_id).budget.elapsed_s
        try:
            state = self.store.get(project_id, task_id)
            remaining = state.budget.max_elapsed_s - initial_elapsed
            if remaining <= 0:
                self.store.stop(project_id, task_id, "Cumulative investigation elapsed-time budget exhausted")
                return
            settings = self.service.repository.settings()
            async with asyncio.timeout(remaining):
                await investigate(str(self.service.repository.root), project_id, task_id,
                                  settings.model_url, settings.planner_model, transport=settings.investigation_transport)
            if self.store.get(project_id, task_id).status == "running":
                self.store.stop(project_id, task_id, "Runner returned without a terminal or paused observation", status="interrupted")
        except asyncio.CancelledError:
            self.store.stop(project_id, task_id, "Runner interrupted after owned execution teardown", status="interrupted")
            raise
        except TimeoutError:
            self.store.stop(project_id, task_id, "Cumulative investigation elapsed-time budget exhausted")
        except Exception as error:
            self.store.stop(project_id, task_id, f"Investigation runner failed: {type(error).__name__}: {error}"[:1500], status="failed")
        finally:
            try:
                # The ledger counts model/tool time. Include host/transport gaps
                # once, preserving all prior runs without charging paused time.
                with self.service.repository.lock:
                    record = self.store._load(project_id, task_id)
                    record.task.budget.elapsed_s = max(record.task.budget.elapsed_s,
                                                       initial_elapsed + time.monotonic() - started)
                    self.store._save(record)
            finally:
                self.tasks.pop((project_id, task_id), None)
                lease.release()

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(self._cancel_owned(project_id, task_id)
                               for project_id, task_id in list(self.tasks)), return_exceptions=True)
