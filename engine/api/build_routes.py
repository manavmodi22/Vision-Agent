"""Human-facing durable build lifecycle; no agent tool can call these approvals."""

from fastapi import APIRouter

from engine.builds.manager import BuildManager
from engine.service import WorkspaceService
from spec.build import BuildContinueRequest, BuildRequest, BuildStatus
from spec.platform import Artifact, ArtifactContent, BuildPlan, PlatformReplay, ToolEvent


def build_router(service: WorkspaceService, manager: BuildManager) -> APIRouter:
    router = APIRouter()

    @router.post("/projects/{project_id}/build")
    async def start(project_id: str, request: BuildRequest) -> BuildStatus:
        return await manager.start(project_id, request.prompt)

    @router.get("/projects/{project_id}/build")
    def status(project_id: str) -> BuildStatus:
        return manager.status(project_id)

    @router.post("/projects/{project_id}/build/continue")
    async def resume(project_id: str, request: BuildContinueRequest) -> BuildStatus:
        return await manager.continue_build(project_id, request)

    @router.get("/projects/{project_id}/build/plan")
    def plan(project_id: str) -> BuildPlan:
        value = manager.status(project_id).plan
        if value is None:
            raise FileNotFoundError("No plan revision has been published yet")
        return value

    @router.get("/projects/{project_id}/build/events")
    def events(project_id: str) -> list[ToolEvent]:
        return manager.status(project_id).tool_events

    @router.get("/projects/{project_id}/build/artifacts")
    def artifacts(project_id: str) -> list[Artifact]:
        references = {reference for event in manager.status(project_id).tool_events
                      for reference in (event.input_artifact_id, event.output_artifact_id) if reference}
        return [manager.store.platform.artifact_content(project_id, reference).artifact for reference in sorted(references)]

    @router.get("/projects/{project_id}/build/artifacts/{artifact_id}")
    def artifact(project_id: str, artifact_id: str) -> ArtifactContent:
        return manager.store.platform.artifact_content(project_id, artifact_id)

    @router.get("/projects/{project_id}/build/replay")
    def replay(project_id: str, execution_id: str | None = None) -> PlatformReplay:
        if execution_id is None:
            execution = manager.status(project_id).execution
            if execution is None:
                raise FileNotFoundError("No execution is available for replay")
            execution_id = execution.id
        return manager.store.platform.replay(project_id, execution_id)

    return router
