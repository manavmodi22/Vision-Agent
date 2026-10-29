import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from engine.alerts.models import AlertConfiguration, AlertDelivery, AlertTarget, SaveAlerts
from engine.alerts.service import AlertService
from engine.alerts.transports import deliver
from engine.service import WorkspaceService
from engine.store.models import EventRecord


class MemoryVault:
    def __init__(self) -> None:
        self.values: dict[str, str | None] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str | None) -> None:
        self.values[key] = value


@contextmanager
def webhook(statuses: list[int]) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append({"headers": dict(self.headers), "payload": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            status = statuses[min(len(received) - 1, len(statuses) - 1)]
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_real_webhook_retry_idempotency_and_credentials(tmp_path: Path) -> None:
    workspace = WorkspaceService(tmp_path)
    project = workspace.create_project("Alert test")
    vault = MemoryVault()
    alerts = AlertService(workspace, vault)
    with webhook([503, 204]) as (port, received):
        target = AlertTarget(id="local", name="Loopback", kind="webhook", url=f"http://127.0.0.1:{port}/events")
        with pytest.raises(ValueError, match="Approve"):
            alerts.save(project.id, SaveAlerts(approved=False, configuration=AlertConfiguration(targets=[target])))
        alerts.save(project.id, SaveAlerts(approved=True,
            configuration=AlertConfiguration(enabled=True, targets=[target]), secrets={"local": "test-secret"}))
        assert "test-secret" not in (workspace.root(project.id) / "alerts.json").read_text()
        queued = alerts.test(project.id, target.id, True)
        assert alerts.process_one()
        pending = alerts.outbox.get(project.id, queued.id)
        assert pending.status == "queued" and pending.attempts == 1
        pending.next_attempt_at = 0
        alerts.outbox.update(pending)
        assert alerts.process_one()
        sent = alerts.outbox.get(project.id, queued.id)
        assert sent.status == "sent" and sent.attempts == 2
        assert len(received) == 2
        assert received[0]["headers"]["Idempotency-Key"] == received[1]["headers"]["Idempotency-Key"]
        assert received[0]["headers"]["Authorization"] == "Bearer test-secret"
        assert received[0]["payload"]["synthetic"] is True


def test_destination_revision_and_deployment_revocation(tmp_path: Path) -> None:
    workspace = WorkspaceService(tmp_path)
    project = workspace.create_project("No outbound requests")
    alerts = AlertService(workspace, MemoryVault())
    configuration = alerts.save(project.id, SaveAlerts(approved=True, configuration=AlertConfiguration(
        enabled=True, targets=[AlertTarget(id="local", name="Loopback", kind="webhook", url="http://127.0.0.1:9/")])))
    queued = alerts.test(project.id, "local", True)
    alerts.save(project.id, SaveAlerts(approved=True, configuration=configuration))
    assert alerts.outbox.get(project.id, queued.id).status == "cancelled"
    event = EventRecord(id="rule1", image_path="image.png", label="rule", confidence=1,
                        payload={"kind": "rule", "event": {"when": "count > 1", "zone": "A"}})
    alerts.enqueue_events(project.id, "stale-deployment", [event])
    assert alerts.process_one()
    assert alerts.outbox.list(project.id)[0].status == "cancelled"


@contextmanager
def protocol_server(handler: Any) -> Iterator[tuple[int, list[bytes]]]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(4)
    captured: list[bytes] = []
    failures: list[Exception] = []

    def run() -> None:
        try:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(4)
                handler(connection, captured)
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        yield server.getsockname()[1], captured
    finally:
        worker.join(timeout=5)
        server.close()
        assert not failures, failures


def test_real_smtp_message_has_stable_id_and_event() -> None:
    def smtp(connection: socket.socket, captured: list[bytes]) -> None:
        stream = connection.makefile("rwb")
        stream.write(b"220 local.test ESMTP\r\n")
        stream.flush()
        while line := stream.readline():
            if line.upper().startswith(b"EHLO"):
                stream.write(b"250-local.test\r\n250 SIZE 1000000\r\n")
            elif line.upper().startswith(b"DATA"):
                stream.write(b"354 Send data\r\n")
                stream.flush()
                message = b""
                while (line := stream.readline()) != b".\r\n":
                    message += line
                captured.append(message)
                stream.write(b"250 accepted\r\n")
            elif line.upper().startswith(b"QUIT"):
                stream.write(b"221 bye\r\n")
                stream.flush()
                break
            else:
                stream.write(b"250 OK\r\n")
            stream.flush()
        stream.close()

    with protocol_server(smtp) as (port, captured):
        target = AlertTarget(id="mail", name="Local SMTP", kind="smtp", host="127.0.0.1", port=port,
            tls_mode="none", from_address="sender@example.test", recipients=["recipient@example.test"])
        delivery = AlertDelivery(id="stable-id", project_id="project", target_id="mail", target_name="SMTP",
            event_id="event", revision=1, condition_key="test", payload={"message": "actual loopback email"})
        deliver(target, delivery, None)
        assert b"stable-id" in captured[0] and b"actual loopback email" in captured[0]


def test_real_mqtt_qos1_publish_receives_ack() -> None:
    def read_packet(connection: socket.socket) -> tuple[int, bytes]:
        header = connection.recv(1)[0]
        size, multiplier = 0, 1
        while True:
            value = connection.recv(1)[0]
            size += (value & 127) * multiplier
            if not value & 128:
                break
            multiplier *= 128
        body = b""
        while len(body) < size:
            body += connection.recv(size - len(body))
        return header, body

    def mqtt(connection: socket.socket, captured: list[bytes]) -> None:
        assert read_packet(connection)[0] == 0x10
        connection.sendall(b"\x20\x02\x00\x00")
        header, body = read_packet(connection)
        assert header & 0xF0 == 0x30 and (header >> 1) & 3 == 1
        topic_length = int.from_bytes(body[:2], "big")
        packet_id = body[2 + topic_length:4 + topic_length]
        captured.append(body[4 + topic_length:])
        connection.sendall(b"\x40\x02" + packet_id)
        assert read_packet(connection)[0] == 0xE0

    with protocol_server(mqtt) as (port, captured):
        target = AlertTarget(id="mqtt", name="Local MQTT", kind="mqtt", host="127.0.0.1", port=port,
                            tls_mode="none", topic="vision/events")
        delivery = AlertDelivery(id="stable-id", project_id="project", target_id="mqtt", target_name="MQTT",
            event_id="event", revision=1, condition_key="test", payload={"message": "actual MQTT publish"})
        deliver(target, delivery, None)
        assert json.loads(captured[0])["message"] == "actual MQTT publish"
