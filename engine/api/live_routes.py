"""Metadata-only live ingress; pixels never pass through the HTTP request body."""
from fastapi import APIRouter, HTTPException

from engine.live import LiveManager
from engine.live.contracts import FrameRequest, FrameResponse, LiveError, LiveStatus, StartRequest


def build_router(manager: LiveManager) -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/live")
    def start(project_id: str, request: StartRequest) -> LiveStatus:
        try:
            return manager.start(project_id, request)
        except LiveError as error:
            raise HTTPException(error.status_code, str(error)) from error

    @router.get("/projects/{project_id}/live/{session_id}")
    def status(project_id: str, session_id: str) -> LiveStatus:
        try:
            return manager.status(project_id, session_id)
        except LiveError as error:
            raise HTTPException(error.status_code, str(error)) from error

    @router.post("/projects/{project_id}/live/{session_id}/frames")
    def frame(project_id: str, session_id: str, request: FrameRequest) -> FrameResponse:
        try:
            return manager.frame(project_id, session_id, request)
        except LiveError as error:
            raise HTTPException(error.status_code, str(error)) from error

    @router.post("/projects/{project_id}/live/{session_id}/stop")
    def stop(project_id: str, session_id: str) -> LiveStatus:
        try:
            return manager.stop(project_id, session_id)
        except LiveError as error:
            raise HTTPException(error.status_code, str(error)) from error

    return router
