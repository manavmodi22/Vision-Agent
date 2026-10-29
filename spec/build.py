"""Neutral describe-to-app API and progress contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from spec.models import EvaluationResult, RunResult
from spec.platform import BuildPlan, ExecutionRun, ToolEvent


class BuildModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuildRequest(BuildModel):
    prompt: str = Field(min_length=1, max_length=8000)


class BuildContinueRequest(BuildModel):
    action: Literal["continue", "improve"] = "continue"
    training_approved: bool = False
    prompt: str | None = Field(default=None, max_length=8000)


class BuildLog(BuildModel):
    at: str
    phase: str
    message: str


class BuildStatus(BuildModel):
    id: str
    project_id: str
    status: Literal["running", "awaiting_clarification", "awaiting_review", "awaiting_improvement",
                    "awaiting_approval", "completed", "failed", "interrupted"]
    phase: str
    next_action: Literal["none", "attach_media", "define_zones", "answer_questions", "review_labels", "configure_evaluation", "approve_training", "approve_deployment", "retry"] = "none"
    message: str
    questions: list[str] = Field(default_factory=list)
    log: list[BuildLog] = Field(default_factory=list)
    preview: RunResult | None = None
    selected_candidate_index: int | None = None
    evaluations: list[EvaluationResult] = Field(default_factory=list)
    acceptance_evaluation: EvaluationResult | None = None
    project: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    plan: BuildPlan | None = None
    execution: ExecutionRun | None = None
    tool_events: list[ToolEvent] = Field(default_factory=list)


class BuildContext(BuildModel):
    image_count: int
    reviewed_count: int
    evaluation_image_count: int
    evaluation_reviewed_count: int
    candidate_count: int
    can_propose_labels: bool
    fixture: bool
    training_eligible: bool
    review_subset_created: bool = False
    comparison_scopes: list[str] = Field(default_factory=list)
