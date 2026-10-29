"""Human dataset and pipeline authoring routes."""
from fastapi import APIRouter
from pydantic import Field, JsonValue

from engine.api.contracts import CandidateRequest, RequestModel
from engine.datasets import (
    DatasetClass,
    DatasetImageDocument,
    DatasetManifest,
    DatasetService,
    DatasetVersion,
)
from engine.service import WorkspaceService
from engine.store.models import Project
from spec.models import Annotation, EvalDataset, PipelineSpec


class SaveImage(RequestModel):
    base_revision: int = Field(ge=0)
    annotation: Annotation


class SaveClasses(RequestModel):
    base_revision: int = Field(ge=0)
    classes: list[DatasetClass] = Field(max_length=200)


class NewVersion(RequestModel):
    name: str = Field(min_length=1, max_length=120)


class ImportCOCO(RequestModel):
    path: str
    replace_existing: bool = False


class Holdout(RequestModel):
    image_ids: list[str] = Field(min_length=10, max_length=50)


class SaveCandidate(RequestModel):
    spec: PipelineSpec
    base_spec: PipelineSpec


class ProposeLabels(CandidateRequest):
    max_frames: int = Field(default=50, ge=1, le=50)


def build_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}")
    datasets = DatasetService(service)

    @router.get("/dataset")
    def manifest(project_id: str) -> DatasetManifest:
        return datasets.manifest(project_id)

    @router.get("/dataset/images/{image_id}")
    def image(project_id: str, image_id: str) -> DatasetImageDocument:
        return datasets.image(project_id, image_id)

    @router.put("/dataset/images/{image_id}")
    def save_image(project_id: str, image_id: str, request: SaveImage) -> DatasetImageDocument:
        return datasets.save_image(project_id, image_id, request.base_revision, request.annotation)

    @router.put("/dataset/classes")
    def classes(project_id: str, request: SaveClasses) -> DatasetManifest:
        return datasets.save_classes(project_id, request.base_revision, request.classes)

    @router.get("/dataset/versions")
    def versions(project_id: str) -> list[DatasetVersion]:
        return datasets.versions(project_id)

    @router.post("/dataset/versions")
    def version(project_id: str, request: NewVersion) -> DatasetVersion:
        return datasets.create_version(project_id, request.name)

    @router.post("/dataset/holdout")
    def holdout(project_id: str, request: Holdout) -> DatasetManifest:
        return datasets.freeze_holdout(project_id, request.image_ids)

    @router.get("/dataset/export-coco")
    def export(project_id: str) -> dict[str, JsonValue]:
        return datasets.export_coco(project_id)

    @router.post("/dataset/import-coco")
    def import_coco(project_id: str, request: ImportCOCO) -> DatasetManifest:
        return datasets.import_coco(project_id, request.path, request.replace_existing)

    @router.put("/candidates/{index}")
    def candidate(project_id: str, index: int, request: SaveCandidate) -> Project:
        return service.update_candidate(project_id, index, request.spec, request.base_spec)

    @router.post("/propose-labels")
    def proposals(project_id: str, request: ProposeLabels) -> EvalDataset:
        return service.propose_labels(project_id, request.candidate_index, request.max_frames)

    return router
