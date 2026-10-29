"""Human-only evidence configuration and selected-candidate acceptance actions."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engine.api.contracts import CandidateRequest
from engine.builds.manager import BuildManager
from engine.eval.protocol import (
    acceptance_blockers,
    read_configuration,
    read_protocol,
    save_configuration,
)
from engine.service import WorkspaceService
from spec.evaluation import (
    EvaluationConfiguration,
    EvaluationConfigurationUpdate,
    EvaluationProtocol,
)
from spec.models import EvaluationResult


class EvaluationReadiness(BaseModel):
    candidate_index: int
    acceptance_available: bool
    acceptance_blockers: list[str]
    current_acceptance: EvaluationResult | None = None
    acceptance_replay_available: bool = False


def evaluation_router(service: WorkspaceService, manager: BuildManager) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/evaluation")

    @router.get("/config")
    def configuration(project_id: str) -> EvaluationConfiguration:
        with service.repository.lock:
            return read_configuration(service.root(project_id), service.annotations(project_id))

    @router.put("/config")
    def configure(project_id: str, request: EvaluationConfigurationUpdate) -> EvaluationConfiguration:
        with service.repository.lock:
            before = read_configuration(service.root(project_id), service.annotations(project_id)).revision
            if request.expected_revision != before:
                raise HTTPException(status_code=409, detail="Evaluation configuration changed; reload before saving")
            result = save_configuration(service.root(project_id), service.annotations(project_id), request)
            project = service.get_project(project_id)
            if result.revision != before:
                service.invalidate(project)
                service.repository.save(project)
            return result

    @router.get("/readiness")
    def readiness(project_id: str, candidate_index: int = 0) -> EvaluationReadiness:
        with service.repository.lock:
            project = service.get_project(project_id)
            blockers = acceptance_blockers(service.root(project_id), service.annotations(project_id),
                                           project.candidates, candidate_index)
            current = service.current_acceptance(project_id, candidate_index) if 0 <= candidate_index < len(project.candidates) else None
            return EvaluationReadiness(candidate_index=candidate_index, acceptance_available=not blockers and current is None,
                                       acceptance_blockers=blockers if current is None else [], current_acceptance=current,
                                       acceptance_replay_available=current is not None)

    @router.get("/protocols/{protocol_id}")
    def protocol(project_id: str, protocol_id: str) -> EvaluationProtocol:
        return read_protocol(service.root(project_id), protocol_id)

    @router.post("/acceptance")
    def acceptance(project_id: str, request: CandidateRequest) -> EvaluationResult:
        with service.repository.lock:
            try:
                active = manager.store.get(project_id)
            except FileNotFoundError:
                active = None
            if active is not None and active.view.status == "running":
                raise ValueError("Wait for the active build before evaluating reserved acceptance evidence")
            cached = service.current_acceptance(project_id, request.candidate_index)
            if cached is not None:
                return cached
            protocol = service.freeze_evaluation(project_id, [request.candidate_index], "acceptance")
        result = service.evaluate(project_id, request.candidate_index, protocol.id)
        manager.acceptance_scored(project_id, request.candidate_index, result)
        return result

    return router
