"""Human-reviewed, registry-bound capability installation and validation contracts."""
from typing import Literal

from pydantic import Field

from spec.capabilities import CapabilityHardware, CapabilityLicense, CapabilityReadiness
from spec.models import Contract


class ProvisioningArtifact(Contract):
    filename: str
    source_url: str
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_bytes: int = Field(gt=0, le=4 * 1024**3)


class ProvisioningOption(Contract):
    model_id: str
    capability_id: str
    name: str
    action: Literal["install", "validate", "blocked"]
    installed: bool
    download_bytes: int = Field(ge=0)
    blockers: list[str] = Field(default_factory=list)


class ProvisioningOptions(Contract):
    options: list[ProvisioningOption]


class ProvisioningPlan(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: str
    model_id: str
    capability_id: str
    name: str
    action: Literal["install", "validate"]
    artifacts: list[ProvisioningArtifact]
    license: CapabilityLicense
    source_revision: str
    target_directory: str
    total_download_bytes: int = Field(ge=0)
    max_duration_s: int = Field(gt=0, le=900)
    hardware: CapabilityHardware
    readiness: CapabilityReadiness
    blockers: list[str] = Field(default_factory=list)
    runtime_snapshot: dict[str, str]
    existing_installation_hash: str | None = None


class ProvisioningPlanRequest(Contract):
    model_id: str = Field(min_length=1, max_length=100)


class ProvisioningJobRequest(Contract):
    plan_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: bool


class ProvisioningResult(Contract):
    installed: bool
    installation_path: str
    artifact_hashes: dict[str, str]
    smoke_status: Literal["passed", "failed", "not_run"]
    health_receipt_id: str | None = None
    message: str


class ProvisioningJob(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    plan_id: str
    plan_hash: str
    model_id: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"] = "queued"
    phase: Literal["queued", "downloading", "verifying", "installing", "validating", "completed", "failed", "interrupted"] = "queued"
    created_at: str
    updated_at: str
    progress: float = Field(default=0, ge=0, le=1)
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int = Field(ge=0)
    message: str = "Waiting for the approved installation worker"
    error: str | None = None
    result: ProvisioningResult | None = None


class ProvisioningHealth(Contract):
    id: str
    model_id: str
    job_id: str
    plan_hash: str
    created_at: str
    installation_hash: str
    runtime_snapshot: dict[str, str]
    input_description: str = "Generated black RGB image, 640 by 640 pixels; no user media"
    input_sha256: str
    elapsed_s: float = Field(ge=0)
    observation_count: int = Field(ge=0)
    execution_identity_hash: str
    quality_claim: Literal["none"] = "none"
