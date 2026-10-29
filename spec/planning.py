"""Compact capability choices shared by the planner and deterministic executor."""
from typing import Literal

from pydantic import Field, model_validator

from spec.models import Contract

TaskType = Literal["detection", "ocr", "barcode"]


class ModelTrainingProvenance(Contract):
    origin: Literal["upstream_pretrained", "locally_trained", "system_framework", "synthetic", "unknown"]
    initialization: Literal["pretrained_finetune", "random", "not_applicable", "unknown"] = "unknown"
    training_state: Literal["untrained", "optimization_completed", "unknown"] = "unknown"
    use_scope: Literal["upstream_baseline", "user_candidate", "engineering_smoke", "unknown"] = "unknown"
    use_scope_evidence_ref: str | None = None
    base_model_id: str | None = None
    training_samples: int | None = Field(default=None, ge=0)
    epochs_completed: int | None = Field(default=None, ge=0)
    optimizer_steps: int | None = Field(default=None, ge=0)
    preserved_classes: list[str] = Field(default_factory=list)
    evaluation_dataset_recorded: bool = False
    evaluation_status: Literal["none_attached"] = "none_attached"
    provenance_scope: Literal["registry_recorded", "manifest_recorded"]


class PlanningModelOption(Contract):
    capability_id: str
    model_id: str
    adapter_id: str
    task_types: list[TaskType]
    output_contract: Literal["detections/v1", "texts/v1"]
    vocabulary: Literal["open", "closed", "not_applicable"]
    supported_classes: list[str] = Field(default_factory=list)
    synthetic: bool = False
    readiness: Literal["ready", "unchecked"]
    provenance_hashes: dict[str, str] = Field(default_factory=dict)
    version: str | None = None
    limitations: list[str] = Field(default_factory=list)
    training_provenance: ModelTrainingProvenance | None = None
    selection_basis: Literal["default", "explicit_experiment", "requires_explicit_request", "legacy"] = "legacy"
    selection_reason: str | None = None


class BlockedModelOption(Contract):
    capability_id: str
    reason: str


class PlanningOptions(Contract):
    schema_version: Literal["0.1", "0.2", "0.3"] = "0.1"
    snapshot_id: str
    project_id: str
    fixture_source: bool
    detection_constraint: str | None = None
    eligible_models: list[PlanningModelOption]
    blocked_options: list[BlockedModelOption]
    experimental_models: list[PlanningModelOption] = Field(default_factory=list)
    explicit_model_ids: list[str] = Field(default_factory=list)
    request_hash: str | None = None

    @model_validator(mode="after")
    def unique_options(self) -> "PlanningOptions":
        identifiers = [option.capability_id for option in self.eligible_models + self.experimental_models]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Planning capability IDs must be unique")
        if self.schema_version == "0.1" and (self.experimental_models or self.explicit_model_ids or self.request_hash
                or any(option.training_provenance or option.selection_basis != "legacy" or option.selection_reason
                       for option in self.eligible_models)):
            raise ValueError("Legacy options cannot introduce new experimental authorization fields")
        return self


class CandidateModelSelection(Contract):
    candidate_index: int = Field(ge=0, le=2)
    capability_id: str
    model_id: str
    adapter_id: str
    proposed_reason: str
    options_snapshot_id: str
    status: Literal["proposed"] = "proposed"
