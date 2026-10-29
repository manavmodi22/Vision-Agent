"""Explicit phase transitions and budgets; model text is never approval."""

from enum import StrEnum
from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentError(ValueError):
    """A phase, evidence or resource constraint was violated."""


class AgentConflict(AgentError):
    """An active operation or changed inputs prevent a concurrent update."""


class Phase(StrEnum):
    CLARIFY = "clarify"
    PLAN = "plan"
    COMPILE = "compile"
    EVALUATE = "evaluate"
    SPECIALIZE = "specialize"
    DEPLOY = "deploy"
    OPERATE = "operate"
    QUERY = "query"  # Read-only evidence Q&A does not confer deployment permission.


TOOLS: dict[Phase, frozenset[str]] = {
    Phase.CLARIFY: frozenset({"media_import", "frames_sample", "vlm_ask"}),
    Phase.PLAN: frozenset({"blocks_list", "block_schema", "planning_options", "detect_open_vocab", "dataset_context", "suggest_labels", "build_refine", "build_refinement_context"}),
    Phase.COMPILE: frozenset({"pipeline_validate", "pipeline_run"}),
    Phase.EVALUATE: frozenset({"eval_create", "eval_run", "build_freeze_evaluation", "review_queue", "dataset_context", "suggest_labels", "build_context", "build_prepare_review", "build_propose_labels", "pipeline_run"}),
    Phase.SPECIALIZE: frozenset({"train_start", "train_status", "eval_run", "build_freeze_evaluation", "build_context", "build_train", "pipeline_run"}),
    Phase.DEPLOY: frozenset(),  # Only the human-facing API may approve deployment.
    Phase.OPERATE: frozenset({"events_query", "report_make", "review_queue", "build_operate"}),
    Phase.QUERY: frozenset({"evidence_context", "evidence_execute"}),
}


class AgentBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    max_tool_calls: int = Field(default=30, ge=1, le=100)
    max_wall_seconds: float = Field(default=180, gt=0, le=1800, allow_inf_nan=False)
    max_training_minutes: float = Field(default=30, gt=0, le=240, allow_inf_nan=False)
    max_model_calls: int = Field(default=5, ge=1, le=10)
    tool_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    training_minutes: float = Field(default=0, ge=0, allow_inf_nan=False)
    started_at: float = Field(default_factory=time, allow_inf_nan=False)

    def check_time(self, now: float | None = None) -> None:
        elapsed = (time() if now is None else now) - self.started_at
        if elapsed > self.max_wall_seconds:
            raise AgentError("Agent wall-clock budget exceeded; start a new run to continue.")

    def consume_tool(self, now: float | None = None) -> None:
        self.check_time(now)
        if self.tool_calls >= self.max_tool_calls:
            raise AgentError("Agent tool-call budget exceeded.")
        self.tool_calls += 1

    def reserve_training(self, minutes: float) -> None:
        self.check_time()
        if minutes <= 0 or self.training_minutes + minutes > self.max_training_minutes:
            raise AgentError("Training request exceeds the remaining training-minute budget.")
        self.training_minutes += minutes

    def consume_model(self) -> None:
        self.check_time()
        if self.model_calls >= self.max_model_calls:
            raise AgentError("Agent model-call budget exceeded.")
        self.model_calls += 1


class EvaluationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    spec_hash: str = Field(min_length=1)
    dataset_hash: str = Field(min_length=1)
    passed: bool
    sample_count: int = Field(ge=1)
    reviewed: bool
    protocol_id: str | None = None
    protocol_hash: str | None = None
    promotion_eligible: bool = False


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    phase: Phase = Phase.CLARIFY
    budget: AgentBudget = Field(default_factory=AgentBudget)
    brief_confirmed: bool = False
    candidate_count: int = Field(default=0, ge=0, le=3)
    compiled_count: int = Field(default=0, ge=0, le=3)
    evaluation: EvaluationEvidence | None = None
    deployment_approved: bool = False
    override_reason: str | None = None
    approval_scope: Literal["promotion", "local_trial"] | None = None

    def authorize_tool(self, name: str, now: float | None = None) -> None:
        if name not in TOOLS[self.phase]:
            raise AgentError(f"Tool {name!r} is not allowed during {self.phase.value}.")
        self.budget.consume_tool(now)

    def confirm_brief(self, *, confirmed: bool) -> None:
        self._require(Phase.CLARIFY)
        if not confirmed:
            raise AgentError("A human must confirm the task brief before planning.")
        self.brief_confirmed = True
        self.phase = Phase.PLAN

    def finish_plan(self, candidate_count: int) -> None:
        self._require(Phase.PLAN)
        if not 1 <= candidate_count <= 3:
            raise AgentError("A plan must contain one to three candidates.")
        self.candidate_count = candidate_count
        self.phase = Phase.COMPILE

    def finish_compile(self, compiled_count: int) -> None:
        self._require(Phase.COMPILE)
        if compiled_count != self.candidate_count or compiled_count == 0:
            raise AgentError("Every candidate must compile before evaluation.")
        self.compiled_count = compiled_count
        self.phase = Phase.EVALUATE

    def record_evaluation(self, evidence: EvaluationEvidence) -> None:
        if self.phase not in {Phase.EVALUATE, Phase.SPECIALIZE}:
            raise AgentError("Evaluation evidence can only be recorded during evaluation.")
        if not evidence.reviewed:
            raise AgentError("Evaluation requires human-reviewed labels.")
        self.evaluation = evidence
        self.deployment_approved = False
        self.override_reason = None
        self.approval_scope = None
        self.phase = Phase.DEPLOY if evidence.passed else Phase.EVALUATE

    def specialize(self, training_minutes: float) -> None:
        self._require(Phase.EVALUATE)
        if self.evaluation is None:
            raise AgentError("Evaluate the current model before requesting specialization.")
        self.budget.reserve_training(training_minutes)
        self.phase = Phase.SPECIALIZE

    def approve_deployment(
        self, *, spec_hash: str, dataset_hash: str, human_approved: bool,
        override_reason: str | None = None,
        protocol_id: str | None = None, protocol_hash: str | None = None,
        approval_scope: Literal["promotion", "local_trial"] = "promotion",
    ) -> None:
        if self.phase not in {Phase.DEPLOY, Phase.EVALUATE}:
            raise AgentError("Deployment is unavailable in the current phase.")
        evidence = self.evaluation
        if evidence is None or not evidence.reviewed:
            raise AgentError("Reviewed evaluation evidence is required before deployment.")
        if (evidence.spec_hash, evidence.dataset_hash) != (spec_hash, dataset_hash):
            raise AgentError("Evaluation is stale: the pipeline or dataset has changed.")
        if not human_approved:
            raise AgentError("A human deployment click is required, including for passing models.")
        if (not evidence.protocol_id or not evidence.protocol_hash
                or (evidence.protocol_id, evidence.protocol_hash) != (protocol_id, protocol_hash)):
            raise AgentError("A current frozen evaluation protocol is required before approval.")
        reason = override_reason.strip() if override_reason else None
        if approval_scope == "local_trial" and (not reason or len(reason) < 10):
            raise AgentError("A bounded local trial requires an explicit reason of at least 10 characters.")
        if approval_scope == "promotion" and not evidence.promotion_eligible:
            raise AgentError("The evidence does not qualify for promotion; configure independent acceptance or explicitly approve a local trial.")
        if not evidence.passed and approval_scope == "promotion":
            raise AgentError("The target was missed; only an explicitly approved local trial is available.")
        self.override_reason = reason
        self.approval_scope = approval_scope
        self.deployment_approved = True
        self.phase = Phase.OPERATE

    def invalidate_evidence(self) -> None:
        self.evaluation = None
        self.deployment_approved = False
        self.override_reason = None
        self.approval_scope = None
        self.compiled_count = 0
        self.phase = Phase.COMPILE if self.candidate_count else Phase.CLARIFY

    def _require(self, phase: Phase) -> None:
        if self.phase != phase:
            raise AgentError(f"Expected phase {phase.value}; current phase is {self.phase.value}.")
