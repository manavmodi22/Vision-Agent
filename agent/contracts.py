"""Compact model decisions and compiled planner outputs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec.models import PipelineSpec


class PatternChoice(BaseModel):
    """Local models choose known patterns and bounded parameters, never graph code."""

    model_config = ConfigDict(extra="forbid")
    use_case: Literal["custom", "pallets", "damage", "labels"]
    pipeline_type: Literal["detection", "ocr", "barcode"] = "detection"
    model_capability_id: str | None = None  # Legacy saved decisions retain host-selected semantics.
    model_reason: str | None = Field(default=None, max_length=500)
    objects: list[str] = Field(default_factory=list, max_length=20)
    min_confidence: float = Field(default=0.4, ge=0, le=1)
    count_threshold: int | None = Field(default=None, ge=0, le=10000)
    count_operator: Literal[">=", "<=", ">", "<", "==", "!="] = ">="
    hold_seconds: float = Field(default=0, ge=0, le=3600)
    expected_text: str | None = Field(default=None, max_length=500)
    match_mode: Literal["contains", "exact"] = "contains"
    match_emit: Literal["all", "matched", "mismatched"] = "all"
    use_zones: bool = False
    zone_ids: list[str] = Field(default_factory=list, max_length=20)
    metric: Literal["count_mae", "precision", "recall", "text_accuracy"]
    target: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_choice(self) -> "PatternChoice":
        if self.metric != "count_mae" and self.target > 1:
            raise ValueError("Ratio metric targets must be between zero and one.")
        reading = self.use_case == "labels" or self.pipeline_type in {"ocr", "barcode"}
        if self.use_case == "labels" and not self.expected_text:
            raise ValueError("A label pipeline needs expected_text; otherwise ask a clarifying question.")
        if reading and self.metric != "text_accuracy":
            raise ValueError("Label patterns require text_accuracy.")
        if self.use_case == "custom" and not reading and not self.objects:
            raise ValueError("A custom detector needs object classes; use the saved ontology or ask which objects to detect.")
        if reading and (self.use_zones or self.zone_ids):
            raise ValueError("Object-count regions do not apply to an OCR/barcode reader")
        if self.zone_ids:
            self.use_zones = True
        if len(set(self.zone_ids)) != len(self.zone_ids) or any(not name.strip() or len(name) > 80 for name in self.zone_ids):
            raise ValueError("Requested region names must be nonempty and unique")
        return self


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "required": ["message", "questions", "choices"],
    })
    message: str = Field(min_length=1, max_length=2000)
    questions: list[str] = Field(default_factory=list, max_length=3)
    choices: list[PatternChoice] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_next_step(self) -> "PlanDecision":
        if not self.questions and not self.choices:
            raise ValueError("Choose one to three patterns or ask up to three questions.")
        if self.questions and self.choices:
            raise ValueError("Ask clarifying questions OR propose candidates; do not do both in one decision.")
        if any(not question.strip() for question in self.questions):
            raise ValueError("Questions cannot be blank.")
        return self


class CustomPatternChoice(PatternChoice):
    use_case: Literal["custom"] = "custom"


class CustomPlanDecision(BaseModel):
    """Custom authoring schema does not offer unrelated warehouse preset choices."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"required": ["message", "questions", "choices"]})
    message: str = Field(min_length=1, max_length=2000)
    questions: list[str] = Field(default_factory=list, max_length=3)
    choices: list[CustomPatternChoice] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_next_step(self) -> "CustomPlanDecision":
        PlanDecision.model_validate(self.model_dump(mode="json"))
        return self


class PlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=6000)
    questions: list[str] = Field(default_factory=list, max_length=3)
    candidates: list[PipelineSpec] = Field(default_factory=list, max_length=3)
    tool_calls: int = Field(default=0, ge=0)
    elapsed_s: float = Field(default=0, ge=0)
    operation_id: str | None = None
    needs_zones: bool = False

    @model_validator(mode="after")
    def require_next_step(self) -> "PlanResult":
        if not self.questions and not self.candidates:
            raise ValueError("Return clarifying questions or at least one candidate.")
        if any(not question.strip() for question in self.questions):
            raise ValueError("Clarifying questions cannot be blank.")
        if self.needs_zones and (not self.questions or self.candidates):
            raise ValueError("A region checkpoint needs instructions and cannot contain a guessed spatial pipeline")
        return self
