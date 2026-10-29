"""Durable project and evidence records. Public wire contract uses snake_case."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from spec.investigation import InvestigationTransport
from spec.models import EvaluationResult, PipelineSpec


def now() -> str:
    return datetime.now(UTC).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(Record):
    role: Literal["user", "assistant", "system"]
    content: str


class Project(Record):
    id: str
    name: str
    use_case: Literal["custom", "pallets", "damage", "labels"] = "custom"
    status: str = "draft"
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    media: list[str] = Field(default_factory=list)
    brief: str = ""
    clarification_count: int = Field(default=0, ge=0, le=3)
    candidates: list[PipelineSpec] = Field(default_factory=list)
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    synthetic: bool = False
    fixture: bool = False
    data_origin: str = "User imported media"
    deployment_id: str | None = None
    approval_scope: Literal["promotion", "local_trial"] | None = None
    trial_limits: dict[str, int] = Field(default_factory=dict)


class EventRecord(Record):
    id: str
    created_at: str = Field(default_factory=now)
    image_path: str
    crop_path: str | None = None
    label: str
    confidence: float = Field(ge=0, le=1)
    counts: dict[str, int] = Field(default_factory=dict)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ReviewRecord(Record):
    id: str
    image_path: str
    reason: str
    status: Literal["pending", "accepted", "skipped"] = "pending"


class Deployment(Record):
    id: str
    candidate_index: int
    spec_hash: str
    dataset_hash: str
    approved_at: str = Field(default_factory=now)
    override_reason: str | None = None
    synthetic: bool
    protocol_id: str | None = None
    protocol_hash: str | None = None
    approval_scope: Literal["legacy", "promotion", "local_trial"] = "legacy"
    trial_limits: dict[str, int] = Field(default_factory=dict)


class Settings(Record):
    model_url: str = "http://localhost:1234/v1"
    planner_model: str = ""
    investigation_transport: InvestigationTransport = "structured_json"
    vlm_model: str = ""
    vlm_url: str = "http://127.0.0.1:1235/v1"
    allow_agpl: bool = False

    @field_validator("model_url", "vlm_url")
    @classmethod
    def local_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Model server must use a local http URL (localhost, 127.0.0.1 or ::1)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Model URL cannot contain credentials, query or fragment")
        return value.rstrip("/")

    @field_validator("allow_agpl")
    @classmethod
    def supported_license_policy(cls, value: bool) -> bool:
        if value:
            raise ValueError("AGPL model adapters are not installed in this build")
        return value
