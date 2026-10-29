"""Explicit versioned investigation endpoints, separate from legacy build routing."""
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException
from filelock import Timeout
from pydantic import Field

from engine.investigations.manager import InvestigationManager, InvestigationSnapshot
from engine.investigations.store import InvestigationConflict
from spec.investigation import InvestigationBudget, TaskState
from spec.models import Contract


class StartInvestigation(Contract):
    runtime_version: Literal["a0.1"]
    objective: str = Field(min_length=1, max_length=8000)
    client_request_id: str = Field(min_length=1, max_length=128)
    budget: InvestigationBudget | None = None


class ResumeInvestigation(Contract):
    expected_revision: int = Field(strict=True, ge=0)
    answer: str | None = Field(default=None, min_length=1, max_length=8000)


class ControlInvestigation(Contract):
    expected_revision: int = Field(strict=True, ge=0)
    action: Literal["pause", "cancel"]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except (InvestigationConflict, Timeout) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Project or investigation not found") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def build_router(manager: InvestigationManager) -> APIRouter:
    router = APIRouter(tags=["investigations"])

    @router.post("/projects/{project_id}/investigations")
    async def start(project_id: str, request: StartInvestigation) -> TaskState:
        with _errors():
            return await manager.start(project_id, request.objective, request.client_request_id, request.budget)

    @router.get("/projects/{project_id}/investigations")
    def list_tasks(project_id: str) -> list[TaskState]:
        with _errors():
            return manager.list(project_id)

    @router.get("/projects/{project_id}/investigations/{task_id}")
    def snapshot(project_id: str, task_id: str) -> InvestigationSnapshot:
        with _errors():
            return manager.snapshot(project_id, task_id)

    @router.post("/projects/{project_id}/investigations/{task_id}/resume")
    async def resume(project_id: str, task_id: str, request: ResumeInvestigation) -> TaskState:
        with _errors():
            return await manager.resume(project_id, task_id, request.expected_revision, request.answer)

    @router.post("/projects/{project_id}/investigations/{task_id}/control")
    async def control(project_id: str, task_id: str, request: ControlInvestigation) -> TaskState:
        with _errors():
            return await manager.control(project_id, task_id, request.expected_revision, request.action)

    return router
