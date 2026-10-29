"""Small typed actions and durable receipts for the A0 investigation loop."""
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from spec.authoring import GraphCandidate
from spec.inference import SHA256, Box
from spec.inference_requests import BarcodeRequest, DetectionRequest, OcrRequest
from spec.models import Contract, RunResult

OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]
RecordId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
InvestigationTransport = Literal["structured_json", "decision_function"]


class DiscoverCapabilities(Contract):
    type: Literal["discover_capabilities"]
    query: str = Field(default="", max_length=300)
    kind: Literal["model", "tool"] | None = None
    task_type: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=8, ge=1, le=8)
    cursor: str | None = Field(default=None, max_length=128)


class InspectCapability(Contract):
    type: Literal["inspect_capability"]
    capability_id: str = Field(min_length=1, max_length=120)


class InspectMedia(Contract):
    type: Literal["inspect_media"]
    media_ids: list[OpaqueId] = Field(default_factory=list, max_length=3)
    representation: Literal["metadata", "pixels"] = "metadata"
    limit: int = Field(default=3, ge=1, le=3)
    cursor: str | None = Field(default=None, max_length=128)


class CropTransform(Contract):
    type: Literal["crop"]
    box: Box

    @model_validator(mode="after")
    def positive_area(self) -> "CropTransform":
        if self.box[0] >= self.box[2] or self.box[1] >= self.box[3]:
            raise ValueError("Crop bounds must have positive area")
        return self


class ResizeTransform(Contract):
    type: Literal["resize"]
    width: int = Field(strict=True, ge=1, le=8192)
    height: int = Field(strict=True, ge=1, le=8192)


ProbeTransform = Annotated[CropTransform | ResizeTransform, Field(discriminator="type")]


class DetectionProbeRequest(DetectionRequest):
    task: Literal["detection"] = Field(...)


class OCRProbeRequest(OcrRequest):
    task: Literal["ocr"] = Field(...)


class BarcodeProbeRequest(BarcodeRequest):
    task: Literal["barcode"] = Field(...)


ProbeRequest = Annotated[DetectionProbeRequest | OCRProbeRequest | BarcodeProbeRequest,
                         Field(discriminator="task")]


class RunProbe(Contract):
    type: Literal["run_probe"]
    capability_id: str = Field(min_length=1, max_length=120)
    inspected_descriptor_hash: SHA256
    media_id: OpaqueId
    source_sha256: SHA256
    transforms: list[ProbeTransform] = Field(default_factory=list, max_length=4)
    request: ProbeRequest


class InspectObservation(Contract):
    type: Literal["inspect_observation"]
    observation_id: RecordId
    view: Literal["values", "geometry", "image", "overlay", "error"] = "values"
    limit: int = Field(default=20, ge=1, le=20)
    cursor: str | None = Field(default=None, max_length=128)


class PrepareWorkflow(Contract):
    """Load full graph-authoring schemas for a subsequent typed workflow submission.

    The host then compiles and previews that submitted graph as a saved draft.
    workflow_capabilities lists supported operations, including crop and resize.
    This request itself creates no graph; successful probes do not automatically
    become saved workflows.
    """

    type: Literal["prepare_workflow"]
    evidence_ids: list[RecordId] = Field(default_factory=list, max_length=16)
    summary: str = Field(min_length=1, max_length=1000)


class AskUser(Contract):
    type: Literal["ask_user"]
    question: str = Field(min_length=1, max_length=500)


class Finish(Contract):
    type: Literal["finish"]
    outcome: Literal["blocked", "inconclusive", "draft_ready"]
    evidence_ids: list[RecordId] = Field(default_factory=list, max_length=16)
    summary: str = Field(min_length=1, max_length=1000)
    workflow_revision_id: RecordId | None = None

    @model_validator(mode="after")
    def ready_revision(self) -> "Finish":
        if (self.outcome == "draft_ready") != (self.workflow_revision_id is not None):
            raise ValueError("Only draft_ready requires an explicit previewed workflow revision")
        return self


InvestigationAction = Annotated[DiscoverCapabilities | InspectCapability | InspectMedia | RunProbe |
    InspectObservation | PrepareWorkflow | AskUser | Finish, Field(discriminator="type")]


class NextAction(Contract):
    type: Literal["next_action"] = "next_action"
    state_revision: int = Field(ge=0)
    decision_summary: str = Field(min_length=1, max_length=1000)
    based_on_observation_ids: list[RecordId] = Field(default_factory=list, max_length=32)
    action: InvestigationAction


class ConstructWorkflow(Contract):
    type: Literal["construct_workflow"]
    graph: GraphCandidate
    media_ids: list[OpaqueId] = Field(min_length=1, max_length=3)
    evidence_ids: list[RecordId] = Field(default_factory=list, max_length=16)
    parent_revision_id: RecordId | None = None

    @model_validator(mode="after")
    def unique_media(self) -> "ConstructWorkflow":
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("Workflow preview media IDs must be unique")
        return self


class WorkflowDecision(Contract):
    type: Literal["workflow_decision"]
    state_revision: int = Field(ge=0)
    decision_summary: str = Field(min_length=1, max_length=1000)
    based_on_observation_ids: list[RecordId] = Field(default_factory=list, max_length=32)
    action: ConstructWorkflow


BuilderDecision = Annotated[NextAction | WorkflowDecision, Field(discriminator="type")]
BuilderAction = Annotated[DiscoverCapabilities | InspectCapability | InspectMedia | RunProbe |
    InspectObservation | PrepareWorkflow | AskUser | Finish | ConstructWorkflow, Field(discriminator="type")]


class WorkflowPreviewEvidence(Contract):
    """Required host result subset; model-authored claims never select a revision."""

    workflow_revision_id: RecordId
    spec_hash: SHA256
    preview_spec_hash: SHA256
    preview_media_ids: list[OpaqueId] = Field(min_length=1, max_length=3)
    preview: RunResult
    validated: Literal[True]
    preview_success: Literal[True]

    @model_validator(mode="after")
    def exact_preview(self) -> "WorkflowPreviewEvidence":
        if self.spec_hash != self.preview_spec_hash:
            raise ValueError("Workflow and preview spec hashes must match")
        if len(self.preview.frames) != len(self.preview_media_ids):
            raise ValueError("Workflow preview must contain a result for every selected media ID")
        return self


class InvestigationBudget(Contract):
    max_model_calls: int = Field(default=20, ge=1, le=100)
    max_actions: int = Field(default=16, ge=1, le=100)
    max_probes: int = Field(default=6, ge=0, le=30)
    max_elapsed_s: float = Field(default=900, ge=1, le=7200)
    model_calls: int = Field(default=0, ge=0)
    actions: int = Field(default=0, ge=0)
    probes: int = Field(default=0, ge=0)
    elapsed_s: float = Field(default=0, ge=0)


TaskStatus = Literal["running", "awaiting_input", "blocked", "inconclusive", "interrupted", "failed", "cancelled", "paused", "draft_ready"]
ReceiptStatus = Literal["reserved", "completed", "failed", "interrupted", "cancelled"]
ObservationStatus = Literal["completed", "failed", "interrupted", "cancelled"]


class TaskState(Contract):
    schema_version: Literal["a0.1"] = "a0.1"
    id: RecordId
    project_id: str
    objective: str = Field(min_length=1, max_length=8000)
    revision: int = Field(default=0, ge=0)
    status: TaskStatus = "running"
    stage: Literal["investigating", "workflow"] = "investigating"
    selected_workflow_revision: RecordId | None = None
    preview_observation_id: RecordId | None = None
    budget: InvestigationBudget = Field(default_factory=InvestigationBudget)
    pending_action_id: RecordId | None = None
    pending_model_call_id: RecordId | None = None
    latest_observation_ids: list[RecordId] = Field(default_factory=list)
    question: str | None = None
    stop_reason: str | None = None
    user_answers: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ModelCall(Contract):
    id: RecordId
    state_revision: int
    model: str
    context: dict[str, JsonValue]
    visible_observation_ids: list[RecordId] = Field(default_factory=list)
    status: Literal["running", "completed", "failed", "interrupted"] = "running"
    response: dict[str, JsonValue] | None = None
    error: str | None = None
    started_at: str
    ended_at: str | None = None


class ActionReceipt(Contract):
    id: RecordId
    model_call_id: RecordId
    decision: BuilderDecision
    status: ReceiptStatus = "reserved"
    observation_id: RecordId | None = None
    started_at: str
    ended_at: str | None = None

    @property
    def action(self) -> BuilderAction:
        return self.decision.action


class Observation(Contract):
    id: RecordId
    action_id: RecordId
    result_type: str
    status: ObservationStatus
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    error: dict[str, JsonValue] | str | None = None
    created_at: str
