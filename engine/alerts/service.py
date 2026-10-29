"""Explicit target approval and durable delivery. No previews send alerts."""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from engine.alerts.models import AlertConfiguration, AlertDelivery, SaveAlerts
from engine.alerts.outbox import Outbox
from engine.alerts.secrets import KeychainVault, SecretVault
from engine.alerts.transports import DeliveryError, deliver
from engine.store.models import EventRecord, now
from engine.store.repository import atomic_model

if TYPE_CHECKING:
    from engine.service import WorkspaceService


class AlertService:
    def __init__(self, workspace: WorkspaceService, vault: SecretVault | None = None) -> None:
        self.workspace = workspace
        self.vault = vault or KeychainVault()
        self.outbox = Outbox(workspace.repository.root)
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

    def configuration(self, project_id: str) -> AlertConfiguration:
        path = self.workspace.root(project_id) / "alerts.json"
        return AlertConfiguration.model_validate_json(path.read_text()) if path.exists() else AlertConfiguration()

    def save(self, project_id: str, request: SaveAlerts) -> AlertConfiguration:
        if not request.approved:
            raise ValueError("Approve alert destinations before saving")
        with self.workspace.repository.lock:
            current = self.configuration(project_id)
            if request.configuration.revision != current.revision:
                raise ValueError("Alert settings changed; reload before saving")
            configuration = request.configuration.model_copy(deep=True)
            known = {target.id for target in configuration.targets}
            if set(request.secrets) - known:
                raise ValueError("Credentials must belong to a configured target")
            old = {target.id: target for target in current.targets}
            for target in configuration.targets:
                key = f"{project_id}/{target.id}"
                if target.id in request.secrets:
                    self.vault.set(key, request.secrets[target.id])
                    target.has_secret = bool(request.secrets[target.id])
                else:
                    target.has_secret = old[target.id].has_secret if target.id in old else False
            configuration.revision = current.revision + 1
            atomic_model(self.workspace.root(project_id) / "alerts.json", configuration)
            self.outbox.cancel_revision(project_id, configuration.revision)
            return configuration

    def test(self, project_id: str, target_id: str, approved: bool) -> AlertDelivery:
        if not approved:
            raise ValueError("Approve sending a test message")
        with self.workspace.repository.lock:
            configuration = self.configuration(project_id)
            target = next((t for t in configuration.targets if t.id == target_id and t.enabled), None)
            if target is None:
                raise ValueError("Save an enabled destination before testing it")
            identifier = uuid.uuid4().hex
            delivery = AlertDelivery(id=identifier, project_id=project_id, target_id=target.id,
                target_name=target.name, event_id=identifier, revision=configuration.revision,
                condition_key="test", test=True,
                payload={"type": "visionapp.test", "message": "User-requested VisionApp connection test",
                         "project_id": project_id, "synthetic": True})
            self.outbox.enqueue(delivery)
            return delivery

    def enqueue_events(self, project_id: str, deployment_id: str,
                       events: list[EventRecord]) -> None:
        configuration = self.configuration(project_id)
        if not configuration.enabled:
            return
        for event in events:
            if event.payload.get("kind") != "rule":
                continue
            details = event.payload.get("event")
            # Counts/confidence can change every frame; debounce by the rule and zone.
            condition = ({key: details.get(key) for key in ("rule", "zone", "when", "condition", "alert_target")}
                         if isinstance(details, dict) else {"condition": str(details)})
            key = hashlib.sha256(json.dumps(condition, sort_keys=True).encode()).hexdigest()
            for target in configuration.targets:
                if not target.enabled:
                    continue
                delivery = AlertDelivery(id=uuid.uuid4().hex, project_id=project_id,
                    target_id=target.id, target_name=target.name, event_id=event.id,
                    revision=configuration.revision, deployment_id=deployment_id,
                    condition_key=key, payload={"type": "visionapp.rule", "project_id": project_id,
                        "deployment_id": deployment_id, "event": event.model_dump(mode="json")})
                self.outbox.enqueue(delivery, configuration.minimum_interval_s)

    def retry(self, project_id: str, delivery_id: str, approved: bool) -> AlertDelivery:
        if not approved:
            raise ValueError("Approve retrying this failed delivery")
        with self.workspace.repository.lock:
            delivery = self.outbox.get(project_id, delivery_id)
            if delivery.status != "failed":
                raise ValueError("Only failed deliveries can be retried")
            if delivery.revision != self.configuration(project_id).revision:
                raise ValueError("The destination changed; send a new test instead")
            delivery.status = "queued"
            delivery.attempts = 0
            delivery.next_attempt_at = 0
            delivery.error = None
            self.outbox.update(delivery)
            return delivery

    def process_one(self) -> bool:
        delivery = self.outbox.claim()
        if delivery is None:
            return False
        try:
            with self.workspace.repository.lock:
                configuration = self.configuration(delivery.project_id)
                project = self.workspace.get_project(delivery.project_id)
                target = next((t for t in configuration.targets if t.id == delivery.target_id and t.enabled), None)
                if (configuration.revision != delivery.revision or target is None
                        or (not delivery.test and (not configuration.enabled or project.deployment_id != delivery.deployment_id))):
                    delivery.status = "cancelled"
                    delivery.error = "Destination or deployment approval changed before delivery"
                    self.outbox.update(delivery)
                    return True
                secret = self.vault.get(f"{delivery.project_id}/{target.id}") if target.has_secret else None
            deliver(target, delivery, secret)
            delivery.status = "sent"
            delivery.sent_at = now()
            delivery.error = None
        except DeliveryError as error:
            delivery.error = str(error)
            delivery.status = "queued" if error.retryable and delivery.attempts < 3 else "failed"
            delivery.next_attempt_at = time.time() + 2 ** delivery.attempts
        except Exception:
            delivery.status = "failed"
            delivery.error = "Delivery could not complete; check the destination and credential settings"
        self.outbox.update(delivery)
        return True

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._work, name="visionapp-alerts", daemon=True)
        self.worker.start()

    def _work(self) -> None:
        lease = FileLock(self.workspace.repository.root / ".alerts-worker.lock", timeout=0)
        try:
            with lease:
                self.outbox.recover()
                while not self.stop_event.is_set():
                    if not self.process_one():
                        self.stop_event.wait(0.5)
        except Timeout:
            return

    def stop(self) -> None:
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=12)
