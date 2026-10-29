"""Human-only draft review adoption. Deliberately absent from MCP tools."""
from fastapi import APIRouter

from engine.api.investigation_routes import _errors
from engine.investigations.handoff import ReviewHandoff
from engine.service import WorkspaceService
from spec.build import HandoffResult, HandoffStatus
from spec.handoff import AbortHandoff, AcceptHandoff, HandoffProposal, PrepareHandoff


def handoff_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter(tags=["investigation-review"])
    handoff = ReviewHandoff(service)

    @router.post("/projects/{project_id}/investigations/{task_id}/handoff/prepare")
    def prepare(project_id: str, task_id: str, request: PrepareHandoff) -> HandoffProposal:
        with _errors():
            return handoff.prepare(project_id, task_id, request)

    @router.post("/projects/{project_id}/investigations/{task_id}/handoff/accept")
    def accept(project_id: str, task_id: str, request: AcceptHandoff) -> HandoffResult:
        with _errors():
            return handoff.accept(project_id, task_id, request)

    @router.get("/projects/{project_id}/investigations/{task_id}/handoff")
    def status(project_id: str, task_id: str) -> HandoffStatus:
        with _errors():
            return handoff.status(project_id, task_id)

    @router.post("/projects/{project_id}/investigations/{task_id}/handoff/abort")
    def abort(project_id: str, task_id: str, request: AbortHandoff) -> HandoffStatus:
        with _errors():
            return handoff.abort(project_id, task_id, request)

    return router
