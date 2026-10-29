"""Explicit human review/approval boundary; no provisioning MCP authority."""
from fastapi import APIRouter

from engine.provisioning import ProvisioningManager
from spec.provisioning import (
    ProvisioningHealth,
    ProvisioningJob,
    ProvisioningJobRequest,
    ProvisioningOptions,
    ProvisioningPlan,
    ProvisioningPlanRequest,
)


def provisioning_router(manager: ProvisioningManager) -> APIRouter:
    router = APIRouter(prefix="/provisioning")

    @router.get("/options")
    def options() -> ProvisioningOptions:
        return manager.options()

    @router.post("/plans")
    def create_plan(request: ProvisioningPlanRequest) -> ProvisioningPlan:
        return manager.create_plan(request.model_id)

    @router.get("/plans/{plan_id}")
    def plan(plan_id: str) -> ProvisioningPlan:
        return manager.plan(plan_id)

    @router.post("/jobs")
    def start(request: ProvisioningJobRequest) -> ProvisioningJob:
        return manager.start(request)

    @router.get("/jobs")
    def jobs(model_id: str | None = None) -> list[ProvisioningJob]:
        return manager.jobs(model_id)

    @router.get("/jobs/{job_id}")
    def job(job_id: str) -> ProvisioningJob:
        return manager.get(job_id)

    @router.get("/health/{receipt_id}")
    def health(receipt_id: str) -> ProvisioningHealth:
        return manager.health(receipt_id)

    return router
