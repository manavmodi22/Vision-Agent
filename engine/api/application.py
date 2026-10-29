"""Native UI boundary: all deployment and label-edit actions are explicit routes."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import JsonValue, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from engine.agent_state import AgentConflict, AgentStateStore
from engine.alerts.service import AlertService
from engine.api.agent_routes import build_router as agent_router
from engine.api.alert_routes import build_router as alert_router
from engine.api.annotation_routes import annotation_router
from engine.api.build_routes import build_router as build_workflow_router
from engine.api.capability_routes import build_router as capability_router
from engine.api.contracts import (
    AskRequest,
    CandidateRequest,
    CreateProject,
    DeployRequest,
    MediaImport,
    PlanRequest,
    ReviewRequest,
    RunMediaRequest,
    RunRequest,
    TrainRequest,
    ZonesRequest,
)
from engine.api.dataset_routes import build_router as dataset_router
from engine.api.evaluation_routes import evaluation_router
from engine.api.handoff_routes import handoff_router
from engine.api.investigation_routes import build_router as investigation_router
from engine.api.live_routes import build_router as live_router
from engine.api.provisioning_routes import provisioning_router
from engine.api.sample_routes import build_router as sample_router
from engine.builds.manager import BuildManager
from engine.datasets import DatasetConflict, DatasetService
from engine.evidence import events_csv
from engine.investigations.handoff_guard import assert_handoff_mutable
from engine.investigations.manager import InvestigationManager
from engine.jobs import Job, JobManager
from engine.live import LiveManager
from engine.provisioning import ProvisioningConflict, ProvisioningManager
from engine.runtime_identity import runtime_identity
from engine.service import WorkspaceService
from engine.store.models import EventRecord, Message, Project, ReviewRecord, Settings
from engine.zones import ZoneState, read_zone_state, save_zone_state
from spec.models import EvalDataset, EvaluationResult, RunResult, Zone

log = logging.getLogger("visionapp.api")


def create_app(data_dir: Path) -> FastAPI:
    service = WorkspaceService(data_dir)
    alerts = AlertService(service)
    live = LiveManager(service)
    builds = BuildManager(service)
    investigations = InvestigationManager(service)
    provisioning = ProvisioningManager(data_dir)
    identity = runtime_identity(data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        alerts.start()
        try:
            yield
        finally:
            await builds.close()
            await investigations.close()
            await run_in_threadpool(provisioning.close)
            await run_in_threadpool(live.close)
            await run_in_threadpool(alerts.stop)

    app = FastAPI(title="VisionApp local engine", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.state.live = live
    app.state.builds = builds
    app.state.investigations = investigations
    app.state.provisioning = provisioning
    jobs = JobManager(service)
    app.include_router(provisioning_router(provisioning))
    app.include_router(evaluation_router(service, builds))
    app.include_router(dataset_router(service))
    app.include_router(annotation_router(service))
    app.include_router(alert_router(alerts))
    app.include_router(agent_router(service))
    app.include_router(live_router(live))
    app.include_router(sample_router(service))
    app.include_router(build_workflow_router(service, builds))
    app.include_router(investigation_router(investigations))
    app.include_router(handoff_router(service))
    app.include_router(capability_router(service))
    agent_states = AgentStateStore(service)

    @app.middleware("http")
    async def pending_handoff(request: Request, call_next: RequestResponseEndpoint) -> Response:
        parts = request.url.path.strip("/").split("/")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and len(parts) >= 2 and parts[0] == "projects":
            is_handoff = len(parts) >= 5 and parts[2] == "investigations" and parts[4] == "handoff"
            if not is_handoff:
                try:
                    with service.repository.lock:
                        assert_handoff_mutable(service.root(parts[1]))
                except AgentConflict as error:
                    return JSONResponse(status_code=409, content={"detail": str(error)})
                except (ValueError, FileNotFoundError):
                    pass  # Preserve the endpoint's normal identifier/not-found response.
        return await call_next(request)

    @app.exception_handler(ProvisioningConflict)
    @app.exception_handler(DatasetConflict)
    @app.exception_handler(AgentConflict)
    async def conflict(request: Request, error: DatasetConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def bad_request(request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(FileNotFoundError)
    async def not_found(request: Request, error: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(error)})

    @app.exception_handler(ValidationError)
    async def invalid_data(request: Request, error: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(Exception)
    async def server_error(request: Request, error: Exception) -> JSONResponse:
        log.exception("Engine operation failed")
        return JSONResponse(status_code=500, content={"detail": f"{type(error).__name__}: {error}"})

    @app.get("/health")
    async def health() -> dict[str, JsonValue]:
        settings = service.repository.settings()
        model_server: dict[str, JsonValue] = {"reachable": False, "models": [], "error": None}
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(settings.model_url + "/models")
                response.raise_for_status()
                data = response.json()
                model_server = {"reachable": True, "models": [item["id"] for item in data.get("data", [])],
                                "error": None}
        except (httpx.HTTPError, ValueError, KeyError) as error:
            model_server["error"] = f"Local model server unavailable: {error}"
        return {"status": "ok", "version": "0.1.0", "model_server": model_server,
                "runtime": dict(identity),
                "capabilities": {"image_folder": True, "recorded_video": True,
                    "apple_vision": bool(os.environ.get("VISION_APP_BINARY")),
                    "camera": False, "screen_capture": False, "training": True,
                    "alerts": True, "native_app": True, "live_frame_ingress": True}}

    @app.get("/projects")
    def projects() -> list[Project]:
        return service.list_projects()

    @app.post("/projects")
    def create(request: CreateProject) -> Project:
        return service.create_project(request.name, request.use_case)

    @app.get("/projects/{project_id}")
    def project(project_id: str) -> Project:
        return service.get_project(project_id)

    @app.post("/projects/{project_id}/media")
    def media(project_id: str, request: MediaImport) -> Project:
        return service.import_media(project_id, request.paths)

    @app.post("/projects/{project_id}/demo")
    def demo(project_id: str) -> Project:
        return service.demo(project_id)

    @app.post("/projects/{project_id}/plan")
    async def plan(project_id: str, request: PlanRequest) -> dict[str, JsonValue]:
        from agent.planner import plan as agent_plan
        from agent.templates import build_template

        project = service.get_project(project_id)
        if not project.media:
            raise ValueError("Import samples before building")
        if request.mode == "template":
            classes = [item.name for item in DatasetService(service).manifest(project_id).classes]
            candidates = build_template(project.use_case, "media", request.model, classes=classes)
            message = "Built an explicitly selected pipeline template. No language model was used."
            questions: list[str] = []
        else:
            settings = service.repository.settings().model_dump(mode="json")
            settings.update({"mcp_data_dir": str(data_dir), "project_id": project_id,
                             "detector_model": request.model, "model": request.model, "use_case": project.use_case, "clarification_count": project.clarification_count})
            context = "\n".join(f"{item.role}: {item.content}" for item in project.messages[-6:])
            prompt = f"Previous conversation:\n{context}\nUser request:\n{request.prompt}" if context else request.prompt
            result = await asyncio.wait_for(agent_plan(prompt, "media", settings), timeout=185)
            candidates, message, questions = result.candidates, result.message, result.questions
        if request.mode == "agent":
            if result.operation_id is None:
                raise ValueError("Planner did not return a durable operation token")
            project = await run_in_threadpool(agent_states.commit_plan, project_id, result.operation_id, result, request.prompt)
        else:
            if candidates:
                await run_in_threadpool(service.save_candidates, project_id, candidates, request.prompt)
            with service.repository.lock:
                project = service.get_project(project_id)
                project.messages += [Message(role="user", content=request.prompt or f"Build {project.use_case} template"),
                                     Message(role="assistant", content=message)]
                service.repository.save(project)
                agent_states.reconcile(project_id, "change")
        return {"message": message, "questions": list(questions), "candidates": [c.model_dump(mode="json", by_alias=True) for c in candidates], "project": project.model_dump(mode="json", by_alias=True)}

    @app.post("/projects/{project_id}/preview")
    def preview(project_id: str, request: CandidateRequest) -> RunResult:
        return service.preview(project_id, request.candidate_index)

    @app.get("/projects/{project_id}/annotations")
    def annotations(project_id: str) -> EvalDataset:
        return service.annotations(project_id)

    @app.put("/projects/{project_id}/annotations")
    def save_annotations(project_id: str, request: EvalDataset) -> EvalDataset:
        return service.save_annotations(project_id, request)

    @app.put("/projects/{project_id}/zones")
    def zones(project_id: str, request: ZonesRequest) -> ZoneState:
        geometry = [Zone.model_validate(zone.model_dump()) for zone in request.zones]
        with service.repository.lock:
            project = service.get_project(project_id)
            result = save_zone_state(service.root(project_id), geometry)
            service.invalidate(project)
            service.repository.save(project)
        return result

    @app.get("/projects/{project_id}/zones")
    def get_zones(project_id: str) -> ZoneState:
        return read_zone_state(service.root(project_id))

    @app.post("/projects/{project_id}/evaluate")
    def evaluate(project_id: str, request: CandidateRequest) -> EvaluationResult:
        result = service.evaluate(project_id, request.candidate_index)
        agent_states.reconcile(project_id, "evaluate")
        return result

    @app.post("/projects/{project_id}/deploy")
    def deploy(project_id: str, request: DeployRequest) -> dict[str, JsonValue]:
        result = service.deploy(project_id, request.candidate_index, request.approved, request.override_reason,
                                approval_scope=request.approval_scope)
        agent_states.reconcile(project_id, "deploy")
        return result

    @app.post("/projects/{project_id}/run")
    def run(project_id: str, request: RunRequest) -> RunResult:
        result = service.run(project_id, request.candidate_index, request.max_frames)
        agent_states.reconcile(project_id, "run")
        return result

    @app.get("/projects/{project_id}/events")
    def events(project_id: str) -> list[EventRecord]:
        return service.events(project_id)

    @app.post("/projects/{project_id}/run-on-media")
    def run_on_media(project_id: str, request: RunMediaRequest) -> RunResult:
        result = service.run(project_id, request.candidate_index, request.max_frames, request.paths)
        agent_states.reconcile(project_id, "run")
        return result

    @app.get("/projects/{project_id}/events.csv", response_class=PlainTextResponse)
    def export_events(project_id: str) -> str:
        return events_csv(service.events(project_id))

    @app.get("/projects/{project_id}/review")
    def review(project_id: str) -> list[ReviewRecord]:
        return service.review(project_id)

    @app.post("/projects/{project_id}/review/{review_id}")
    def review_action(project_id: str, review_id: str, request: ReviewRequest) -> ReviewRecord:
        return service.repository.update_review(project_id, review_id, request.status)

    @app.post("/projects/{project_id}/ask")
    async def ask(project_id: str, request: AskRequest) -> dict[str, JsonValue]:
        from agent.evidence_planner import ask_evidence

        service.get_project(project_id)
        settings = service.repository.settings().model_dump(mode="json")
        settings.update({"project_id": project_id, "mcp_data_dir": str(data_dir)})
        result = await ask_evidence(request.question, settings, timezone=request.timezone)
        return result.model_dump(mode="json")

    @app.post("/projects/{project_id}/train")
    def train(project_id: str, request: TrainRequest) -> Job:
        return jobs.start(project_id, request.candidate_index, request.max_minutes, request.epochs, request.approved)

    @app.get("/projects/{project_id}/jobs/{job_id}")
    def job_status(project_id: str, job_id: str) -> Job:
        return jobs.get(project_id, job_id)

    @app.get("/settings")
    def settings() -> Settings:
        return service.repository.settings()

    @app.put("/settings")
    def set_settings(request: Settings) -> Settings:
        return service.repository.save_settings(request)

    @app.get("/models")
    def models() -> list[dict[str, JsonValue]]:
        from engine.models import list_models
        return list_models()

    @app.get("/blocks")
    def blocks() -> list[dict[str, JsonValue]]:
        from engine.blocks import list_blocks
        return list_blocks()

    return app
