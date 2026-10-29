"""Executable evidence vocabulary: no SQL, arbitrary code, or model-written answers."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TimeScope(EvidenceModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "required": ["period", "amount", "start_date", "end_date"],
    })
    period: Literal["today", "yesterday", "last_hours", "last_days", "between_dates", "all_time"]
    amount: int | None = Field(default=None, ge=1, le=3660)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.period in {"last_hours", "last_days"}:
            if self.amount is None or self.start_date is not None or self.end_date is not None:
                raise ValueError("A rolling period requires only amount, not calendar dates")
        elif self.period == "between_dates":
            if self.start_date is None or self.end_date is None or self.amount is not None:
                raise ValueError("A calendar range requires inclusive start_date and end_date")
            if self.end_date < self.start_date or (self.end_date - self.start_date).days > 3660:
                raise ValueError("Calendar ranges must be ordered and at most 3660 days")
        elif self.amount is not None or self.start_date is not None or self.end_date is not None:
            raise ValueError("This period takes no amount or calendar dates")
        return self


class EvidenceQuery(EvidenceModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "required": ["operation", "labels", "zones", "kind", "time", "min_confidence", "text_contains"],
    })
    operation: Literal["count", "show"]
    labels: list[str] = Field(max_length=20)
    zones: list[str] = Field(max_length=20)
    kind: Literal["detection", "text", "rule"]
    time: TimeScope
    min_confidence: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    text_contains: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def text_kind(self) -> Self:
        if self.text_contains is not None and self.kind != "text":
            raise ValueError("Literal text search requires kind=text")
        if any(not value.strip() or len(value) > 200 for value in self.labels + self.zones):
            raise ValueError("Label and zone values must contain 1–200 characters")
        return self


class EvidenceDecision(EvidenceModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"required": ["query", "questions"]})
    query: EvidenceQuery | None = None
    questions: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def query_or_questions(self) -> Self:
        if (self.query is not None) == bool(self.questions):
            raise ValueError("Return exactly a query or clarification questions")
        if any(not text.strip() or len(text) > 500 for text in self.questions):
            raise ValueError("Clarification questions must contain 1–500 characters")
        return self


class EvidenceContext(EvidenceModel):
    project_id: str
    timezone: str
    reference_time: datetime
    labels: list[str]
    zones: list[str]
    kinds: list[str]
    total_records: int
    earliest_record: str | None
    latest_record: str | None
    time_basis: Literal["record_created_at"] = "record_created_at"
    count_unit: Literal["per_frame_observations"] = "per_frame_observations"


class EvidenceInterpretation(EvidenceModel):
    query: EvidenceQuery
    timezone: str
    start_utc: datetime | None
    end_utc: datetime
    reference_time: datetime
    matched_observations: int
    synthetic_observations: int
    unknown_provenance_observations: int
    evidence_returned: int
    complete_scope: Literal[True] = True
    time_basis: Literal["record_created_at"] = "record_created_at"
    count_unit: Literal["per_frame_observations"] = "per_frame_observations"


class EvidenceAnswer(EvidenceModel):
    answer: str
    evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    interpretation: EvidenceInterpretation | None = None
    questions: list[str] = Field(default_factory=list)
    query_id: str | None = None
