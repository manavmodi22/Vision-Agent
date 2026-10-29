"""Neutral discovery DTOs. Installation, validation eligibility and proof are distinct."""
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from spec.models import Contract


class CapabilityEvidence(Contract):
    kind: Literal["adapter", "package", "file", "platform", "server_metadata", "inference_smoke"]
    subject: str
    outcome: Literal["pass", "fail", "unknown"]
    detail: str
    observed_at: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class CapabilityReadiness(Contract):
    state: Literal["ready", "blocked", "unchecked", "unsupported"]
    reason: str
    checked_at: str
    evidence_scope: Literal["inference_smoke", "prerequisites", "metadata", "not_assessed"]
    evidence: list[CapabilityEvidence] = Field(default_factory=list)


class CapabilityLicense(Contract):
    identifier: str
    code: str | None = None
    weights: str | None = None
    status: Literal["declared", "unverified", "policy_blocked"] = "unverified"
    notes: list[str] = Field(default_factory=list)


class CapabilityProvenance(Contract):
    source_urls: list[str] = Field(default_factory=list)
    revision: str | None = None
    hashes: dict[str, str] = Field(default_factory=dict)
    scope: Literal["bundled_code", "local_manifest", "registry_metadata", "server_metadata", "proposal"]
    notes: list[str] = Field(default_factory=list)


class CapabilityHardware(Contract):
    platforms: list[str] = Field(default_factory=list)
    accelerators: list[str] = Field(default_factory=list)
    required_packages: list[str] = Field(default_factory=list)
    minimum_memory_gib: float | None = Field(default=None, ge=0)
    estimated_disk_bytes: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)


class CapabilityManifest(Contract):
    id: str
    name: str
    kind: Literal["tool", "model"]
    description: str
    availability: Literal["installed", "available_to_install", "unsupported"]
    implemented: bool
    installation_ready: bool
    callable: bool
    task_types: list[str]
    version: str | None = None
    license: CapabilityLicense
    provenance: CapabilityProvenance
    hardware: CapabilityHardware
    side_effects: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    output_schema: dict[str, JsonValue] = Field(default_factory=dict)
    install_method: Literal["bundled", "manual_weights", "reviewed_provisioning", "system_framework", "local_training", "not_implemented"]
    install_instructions: str | None = None
    readiness: CapabilityReadiness

    @model_validator(mode="after")
    def enforce_readiness(self) -> "CapabilityManifest":
        if self.callable and (not self.implemented or not self.installation_ready
                or self.availability != "installed" or self.readiness.state != "ready"):
            raise ValueError("Callable capabilities require installed implementation and verified readiness")
        if self.availability == "unsupported" and (self.implemented or self.installation_ready or self.callable):
            raise ValueError("Unsupported capabilities cannot be executable")
        if self.availability == "available_to_install" and (not self.implemented or self.install_method == "not_implemented"):
            raise ValueError("Available-to-install requires an implemented compatible installation path")
        return self


class CapabilityCatalog(Contract):
    schema_version: Literal["0.1"] = "0.1"
    generated_at: str
    host: dict[str, JsonValue]
    capabilities: list[CapabilityManifest]

    @model_validator(mode="after")
    def unique_ids(self) -> "CapabilityCatalog":
        if len({item.id for item in self.capabilities}) != len(self.capabilities):
            raise ValueError("Capability IDs must be unique")
        return self
