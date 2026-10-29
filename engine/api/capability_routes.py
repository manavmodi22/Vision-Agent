"""Read-only discovery for the native app and orchestrator."""
from fastapi import APIRouter

from engine.capabilities import build_catalog
from engine.service import WorkspaceService
from spec.capabilities import CapabilityCatalog


def build_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter()

    @router.get("/capabilities", response_model=CapabilityCatalog)
    async def capabilities() -> CapabilityCatalog:
        return await build_catalog(service)

    return router
