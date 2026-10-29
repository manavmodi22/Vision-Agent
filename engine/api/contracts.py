"""Human action request models; approval is never accepted through agent tools."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProject(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    use_case: Literal["custom", "pallets", "damage", "labels"] = "custom"


class MediaImport(RequestModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class PlanRequest(RequestModel):
    prompt: str = Field(default="", max_length=8000)
    mode: Literal["template", "agent"] = "template"
    model: str = "owlv2-base-patch16"


class CandidateRequest(RequestModel):
    candidate_index: int = Field(default=0, ge=0, le=2)


class RunRequest(CandidateRequest):
    max_frames: int = Field(default=50, ge=1, le=500)


class RunMediaRequest(RunRequest):
    paths: list[str] = Field(min_length=1, max_length=100)


class DeployRequest(CandidateRequest):
    approved: bool
    override_reason: str | None = Field(default=None, max_length=1000)


class Zone(RequestModel):
    id: str = Field(min_length=1, max_length=50)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=50)


class ZonesRequest(RequestModel):
    zones: list[Zone] = Field(min_length=1, max_length=20)


class ReviewRequest(RequestModel):
    status: Literal["accepted", "skipped"]


class AskRequest(RequestModel):
    question: str = Field(min_length=1, max_length=2000)
    timezone: str | None = Field(default=None, max_length=100)


class TrainRequest(CandidateRequest):
    approved: bool
    max_minutes: float = Field(default=2, gt=0, le=5)
    epochs: int = Field(default=10, ge=1, le=30)
