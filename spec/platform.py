"""Reviewable plans, execution evidence and immutable artifact references."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from spec.models import PipelineSpec
from spec.planning import CandidateModelSelection
from spec.skills import SkillReference


class PlatformModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PlanSnapshot(PlatformModel):
    workspace_hash: str
    dataset_hash: str
    model_hashes: list[str]
    settings_hash: str


class PlanMetric(PlatformModel):
    candidate_index: int
    metric: str
    target: float
    direction: Literal["minimize", "maximize"]


class PlanExperiment(PlatformModel):
    id: str
    phase: str
    description: str
    allowed_tools: list[str]
    candidate_indices: list[int] = Field(default_factory=list)


class HumanCheckpoint(PlatformModel):
    id: str
    phase: str
    description: str
    requires_approval: bool = True


class BuildPlan(PlatformModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    id: str
    project_id: str
    build_id: str | None = None
    operation_id: str
    revision: int = Field(ge=1)
    parent_plan_id: str | None = None
    created_at: str
    content_hash: str
    goal: str
    assumptions: list[str]
    candidates: list[PipelineSpec]
    required_capabilities: list[str]
    experiments: list[PlanExperiment]
    metrics: list[PlanMetric]
    stop_conditions: list[str]
    human_checkpoints: list[HumanCheckpoint]
    snapshot: PlanSnapshot
    skills: list[SkillReference] = Field(default_factory=list)
    revision_reason: str
    planning_options_artifact_id: str | None = None
    model_selections: list[CandidateModelSelection] = Field(default_factory=list)


class ExecutionRun(PlatformModel):
    id: str
    project_id: str
    build_id: str | None = None
    operation_id: str
    plan_id: str
    plan_hash: str
    status: Literal["planned", "running", "paused", "completed", "failed", "interrupted", "stale"] = "planned"
    phase: str
    created_at: str
    updated_at: str
    accepted_snapshot: PlanSnapshot
    error: str | None = None


class Artifact(PlatformModel):
    id: str
    project_id: str
    kind: Literal["tool_input", "tool_output", "preview", "evaluation", "dataset", "model_response", "planning_options"]
    title: str
    created_at: str
    sha256: str
    media_type: str = "application/json"
    size_bytes: int


class ToolEvent(PlatformModel):
    id: str
    sequence: int
    project_id: str
    build_id: str | None = None
    operation_id: str
    execution_id: str | None = None
    plan_id: str | None = None
    call_id: str
    kind: Literal["tool", "llm"]
    stage: Literal["started", "completed", "failed", "interrupted"]
    name: str
    phase: str
    at: str
    duration_ms: float | None = None
    model_identity: str | None = None
    cost_usd: float | None = None
    input_artifact_id: str
    output_artifact_id: str | None = None
    error: str | None = None


class EvaluationReport(PlatformModel):
    id: str
    project_id: str
    execution_id: str
    plan_id: str
    candidate_index: int
    artifact_id: str
    spec_hash: str
    dataset_hash: str
    metric: str
    target: float
    passed: bool
    sample_count: int
    metrics: dict[str, float | None]
    protocol_id: str | None = None
    protocol_hash: str | None = None
    evidence_scope: str = "legacy"
    promotion_eligible: bool = False
    evidence_reasons: list[str] = Field(default_factory=list)


class PlatformReplay(PlatformModel):
    dry_run: Literal[True] = True
    effects_executed: Literal[False] = False
    plan: BuildPlan
    execution: ExecutionRun
    events: list[ToolEvent]
    artifacts: list[Artifact]
    evaluations: list[EvaluationReport]


class ArtifactContent(PlatformModel):
    artifact: Artifact
    content: dict[str, JsonValue]
