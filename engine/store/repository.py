"""Atomic local project documents and parameterized SQLite evidence queries."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import TypeVar

from filelock import FileLock
from pydantic import BaseModel

from engine.store.models import EventRecord, Project, ReviewRecord, Settings, now

T = TypeVar("T", bound=BaseModel)
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def atomic_model(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(value.model_dump_json(indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(exist_ok=True)
        self.lock = FileLock(self.root / ".workspace.lock", timeout=30)
        self.database = self.root / "evidence.sqlite3"
        with self.connection() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, document TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_project_time
                    ON events(project_id, created_at);
                CREATE TABLE IF NOT EXISTS review (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                    image_path TEXT NOT NULL, document TEXT NOT NULL,
                    UNIQUE(project_id, image_path));
            """)

    def connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database, timeout=10)

    def project_root(self, project_id: str) -> Path:
        if not IDENTIFIER.fullmatch(project_id):
            raise ValueError("Invalid project identifier")
        return self.projects_dir / project_id

    def get(self, project_id: str) -> Project:
        path = self.project_root(project_id) / "project.json"
        if not path.is_file():
            raise FileNotFoundError("Project not found")
        return Project.model_validate_json(path.read_text())

    def save(self, project: Project) -> Project:
        project.updated_at = now()
        atomic_model(self.project_root(project.id) / "project.json", project)
        return project

    def list_projects(self) -> list[Project]:
        projects = [Project.model_validate_json(path.read_text())
                    for path in self.projects_dir.glob("*/project.json")]
        return sorted(projects, key=lambda item: item.updated_at, reverse=True)

    def settings(self) -> Settings:
        path = self.root / "settings.json"
        return Settings.model_validate_json(path.read_text()) if path.exists() else Settings()

    def save_settings(self, settings: Settings) -> Settings:
        atomic_model(self.root / "settings.json", settings)
        return settings

    def add_event(self, project_id: str, event: EventRecord) -> None:
        with self.connection() as connection:
            connection.execute("INSERT INTO events VALUES (?,?,?,?)",
                               (event.id, project_id, event.created_at, event.model_dump_json()))

    def events(self, project_id: str, limit: int = 500) -> list[EventRecord]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT document FROM events WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, min(max(limit, 1), 5000)),
            ).fetchall()
        return [EventRecord.model_validate_json(row[0]) for row in rows]

    def add_review(self, project_id: str, record: ReviewRecord) -> None:
        with self.connection() as connection:
            connection.execute("INSERT OR IGNORE INTO review VALUES (?,?,?,?)",
                               (record.id, project_id, record.image_path, record.model_dump_json()))

    def review(self, project_id: str) -> list[ReviewRecord]:
        with self.connection() as connection:
            rows = connection.execute("SELECT document FROM review WHERE project_id=?",
                                      (project_id,)).fetchall()
        return [ReviewRecord.model_validate_json(row[0]) for row in rows]

    def update_review(self, project_id: str, review_id: str, status: str) -> ReviewRecord:
        with self.connection() as connection:
            row = connection.execute("SELECT document FROM review WHERE project_id=? AND id=?",
                                     (project_id, review_id)).fetchone()
            if row is None:
                raise FileNotFoundError("Review item not found")
            value = json.loads(row[0])
            value["status"] = status
            record = ReviewRecord.model_validate(value)
            connection.execute("UPDATE review SET document=? WHERE project_id=? AND id=?",
                               (record.model_dump_json(), project_id, review_id))
        return record
