"""Durable outbox; transport acknowledgment and event persistence are distinct."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from engine.alerts.models import AlertDelivery


class Outbox:
    def __init__(self, root: Path) -> None:
        self.path = root / "alerts.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    target_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    event_id TEXT NOT NULL, condition_key TEXT NOT NULL,
                    created_epoch REAL NOT NULL, status TEXT NOT NULL,
                    next_attempt REAL NOT NULL, document TEXT NOT NULL,
                    UNIQUE(project_id,target_id,revision,event_id));
                CREATE INDEX IF NOT EXISTS pending_delivery ON deliveries(status,next_attempt);
                CREATE INDEX IF NOT EXISTS condition_history
                    ON deliveries(project_id,target_id,revision,condition_key,created_epoch);
            """)

    def connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def enqueue(self, delivery: AlertDelivery, interval: float = 0) -> bool:
        stamp = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if interval:
                recent = db.execute("""SELECT id FROM deliveries WHERE project_id=? AND target_id=?
                    AND revision=? AND condition_key=? AND status!='cancelled' AND created_epoch>? LIMIT 1""",
                    (delivery.project_id, delivery.target_id, delivery.revision,
                     delivery.condition_key, stamp - interval)).fetchone()
                if recent:
                    return False
            pending = db.execute("SELECT COUNT(*) FROM deliveries WHERE status IN ('queued','sending')").fetchone()[0]
            if pending >= 5000:
                raise ValueError("Alert queue is full; inspect failed deliveries before recording more alerts")
            cursor = db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
                (delivery.id, delivery.project_id, delivery.target_id, delivery.revision,
                 delivery.event_id, delivery.condition_key, stamp, delivery.status,
                 delivery.next_attempt_at, delivery.model_dump_json()))
            return cursor.rowcount == 1

    def get(self, project_id: str, delivery_id: str) -> AlertDelivery:
        with self.connection() as db:
            row = db.execute("SELECT document FROM deliveries WHERE project_id=? AND id=?",
                             (project_id, delivery_id)).fetchone()
        if row is None:
            raise FileNotFoundError("Alert delivery not found")
        return AlertDelivery.model_validate_json(row[0])

    def list(self, project_id: str) -> list[AlertDelivery]:
        with self.connection() as db:
            rows = db.execute("SELECT document FROM deliveries WHERE project_id=? ORDER BY created_epoch DESC LIMIT 500",
                              (project_id,)).fetchall()
        return [AlertDelivery.model_validate_json(row[0]) for row in rows]

    def update(self, delivery: AlertDelivery) -> None:
        with self.connection() as db:
            db.execute("UPDATE deliveries SET status=?,next_attempt=?,document=? WHERE id=?",
                (delivery.status, delivery.next_attempt_at, delivery.model_dump_json(), delivery.id))

    def claim(self) -> AlertDelivery | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM deliveries WHERE status='queued' AND next_attempt<=? ORDER BY created_epoch LIMIT 1",
                             (time.time(),)).fetchone()
            if row is None:
                return None
            delivery = AlertDelivery.model_validate_json(row[0])
            delivery.status = "sending"
            delivery.attempts += 1
            db.execute("UPDATE deliveries SET status='sending',document=? WHERE id=?",
                       (delivery.model_dump_json(), delivery.id))
            return delivery

    def recover(self) -> None:
        with self.connection() as db:
            rows = db.execute("SELECT document FROM deliveries WHERE status='sending'").fetchall()
        for row in rows:
            delivery = AlertDelivery.model_validate_json(row[0])
            delivery.status = "queued" if delivery.attempts < 3 else "failed"
            delivery.error = "Engine stopped during delivery; a retry may duplicate remote acceptance"
            delivery.next_attempt_at = 0
            self.update(delivery)

    def cancel_revision(self, project_id: str, revision: int) -> None:
        with self.connection() as db:
            rows = db.execute("SELECT document FROM deliveries WHERE project_id=? AND status IN ('queued','failed')", (project_id,)).fetchall()
        for row in rows:
            delivery = AlertDelivery.model_validate_json(row[0])
            if delivery.revision != revision and delivery.status in {"queued", "failed"}:
                delivery.status = "cancelled"
                delivery.error = "Alert destination configuration changed"
                self.update(delivery)
