"""Required fields at the model boundary; persisted choices keep legacy defaults."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.contracts import PatternChoice, PlanDecision


class ModelPatternChoice(PatternChoice):
    """A model must state comparison behavior instead of acquiring defaults."""

    match_mode: Literal["contains", "exact"] = Field(...)
    match_emit: Literal["all", "matched", "mismatched"] = Field(...)
    record_events: bool = Field(...)
    model_capability_id: str = Field(..., min_length=1, max_length=120)
    model_reason: str = Field(..., min_length=1, max_length=500)


class ModelCustomPatternChoice(ModelPatternChoice):
    use_case: Literal["custom"] = "custom"


class ModelPlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"required": ["message", "questions", "choices"]})
    message: str = Field(min_length=1, max_length=2000)
    questions: list[str] = Field(default_factory=list, max_length=3)
    choices: list[ModelPatternChoice] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_next_step(self) -> "ModelPlanDecision":
        PlanDecision.model_validate(self.model_dump(mode="json"))
        return self


class ModelCustomPlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"required": ["message", "questions", "choices"]})
    message: str = Field(min_length=1, max_length=2000)
    questions: list[str] = Field(default_factory=list, max_length=3)
    choices: list[ModelCustomPatternChoice] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_next_step(self) -> "ModelCustomPlanDecision":
        PlanDecision.model_validate(self.model_dump(mode="json"))
        return self
