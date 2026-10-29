"""Human-selected complete-label archives; no inference or review approval."""
from fastapi import APIRouter
from pydantic import Field

from engine.api.contracts import RequestModel
from engine.dataset_archive import LabelArchive, LabelArchiveService
from engine.datasets import DatasetManifest
from engine.service import WorkspaceService


class ImportLabels(RequestModel):
    path: str
    base_revision: int = Field(ge=0)
    replace_existing: bool = False


def annotation_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/dataset")
    archives = LabelArchiveService(service)

    @router.get("/export-labels")
    def export_labels(project_id: str) -> LabelArchive:
        return archives.export_labels(project_id)

    @router.post("/import-labels")
    def import_labels(project_id: str, request: ImportLabels) -> DatasetManifest:
        return archives.import_labels(project_id, request.path, request.base_revision, request.replace_existing)

    return router
