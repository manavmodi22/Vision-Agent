"""Evidence policy, provenance and immutable comparison/acceptance protocols."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from spec.models import Contract

GroupId = Annotated[str, Field(min_length=1, max_length=120)]
Split = Literal["unassigned", "train", "validation", "acceptance"]
DataOrigin = Literal["unknown", "real", "synthetic"]
Purpose = Literal["validation", "acceptance"]


class EvidencePolicy(Contract):
    intended_use: str = Field(default="", max_length=2000)
    independent_group_basis: str = Field(default="", max_length=2000)
    coverage_rationale: str = Field(default="", max_length=2000)
    required_acceptance_groups: list[GroupId] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_groups(self) -> EvidencePolicy:
        if len(set(self.required_acceptance_groups)) != len(self.required_acceptance_groups):
            raise ValueError("Required acceptance groups must be unique")
        return self


class EvidenceAssignment(Contract):
    image_path: str = Field(min_length=1, max_length=4096)
    scene_group: GroupId | None = None
    split: Split = "unassigned"
    data_origin: DataOrigin = "unknown"


class EvidenceImage(EvidenceAssignment):
    source_asset_id: str | None = None
    source_sha256: str | None = None
    frame_index: int | None = Field(default=None, ge=0)
    timestamp_s: float | None = Field(default=None, ge=0)
    group_provenance: Literal["unknown", "source_record", "human_declared"] = "unknown"
    exposure_reasons: list[str] = Field(default_factory=list)


class EvaluationConfiguration(Contract):
    revision: str
    images: list[EvidenceImage]
    policy: EvidencePolicy = Field(default_factory=EvidencePolicy)


class EvaluationConfigurationUpdate(Contract):
    expected_revision: str
    assignments: list[EvidenceAssignment] = Field(max_length=5000)
    policy: EvidencePolicy

    @model_validator(mode="after")
    def unique_images(self) -> EvaluationConfigurationUpdate:
        paths = [item.image_path for item in self.assignments]
        if len(set(paths)) != len(paths):
            raise ValueError("Each image may have only one evidence assignment")
        return self


class ProtocolCandidate(Contract):
    candidate_index: int = Field(ge=0)
    spec_hash: str


class EvaluationProtocol(Contract):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    protocol_hash: str
    purpose: Purpose
    created_at: str
    config_revision: str
    dataset_hash: str
    membership_hash: str
    task_signature: str
    metric: str
    target: float = Field(ge=0)
    recipe_version: str
    recipe_hash: str
    candidates: list[ProtocolCandidate] = Field(min_length=1, max_length=3)
    image_paths: list[str] = Field(min_length=1, max_length=500)
    group_ids: list[str]
    policy: EvidencePolicy

    @model_validator(mode="after")
    def acceptance_is_selected(self) -> EvaluationProtocol:
        if self.purpose == "acceptance" and len(self.candidates) != 1:
            raise ValueError("Acceptance tests exactly one already-selected candidate")
        return self
