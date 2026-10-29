from fastapi import APIRouter

from engine.alerts.models import AlertConfiguration, AlertDelivery, Approval, SaveAlerts, TestAlert
from engine.alerts.service import AlertService


def build_router(alerts: AlertService) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}")

    @router.get("/alerts")
    def configuration(project_id: str) -> AlertConfiguration:
        return alerts.configuration(project_id)

    @router.put("/alerts")
    def save(project_id: str, request: SaveAlerts) -> AlertConfiguration:
        return alerts.save(project_id, request)

    @router.get("/alert-deliveries")
    def deliveries(project_id: str) -> list[AlertDelivery]:
        alerts.workspace.get_project(project_id)
        return alerts.outbox.list(project_id)

    @router.post("/alerts/test")
    def test(project_id: str, request: TestAlert) -> AlertDelivery:
        return alerts.test(project_id, request.target_id, request.approved)

    @router.post("/alert-deliveries/{delivery_id}/retry")
    def retry(project_id: str, delivery_id: str, request: Approval) -> AlertDelivery:
        return alerts.retry(project_id, delivery_id, request.approved)

    return router
