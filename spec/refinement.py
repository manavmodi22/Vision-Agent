"""Bounded changes to existing applications; unrelated graph fields stay intact."""
from typing import Literal

from pydantic import Field, model_validator

from spec.models import Contract, PipelineSpec, RunResult

RefinementKind = Literal["confidence", "add_classes", "remove_classes", "replace_classes",
                         "count_rule", "expected_text", "sample_fps", "eval_target", "crop", "resize"]


class RefinementPatch(Contract):
    kind: RefinementKind
    scope: Literal["selected", "all"] | None = None
    block_id: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    confidence: float | None = Field(default=None, ge=0, le=1)
    classes: list[str] = Field(default_factory=list, max_length=64)
    count_threshold: float | None = Field(default=None, ge=0, le=1_000_000_000)
    count_operator: Literal[">=", "<=", "==", "!=", ">", "<"] | None = None
    hold_s: float | None = Field(default=None, ge=0, le=86400)
    expected_text: str | None = Field(default=None, min_length=1, max_length=256)
    match_mode: Literal["exact", "contains"] | None = None
    fps: float | None = Field(default=None, gt=0, le=60)
    eval_metric: Literal["count_mae", "precision", "recall", "text_accuracy"] | None = None
    eval_target: float | None = Field(default=None, ge=0)
    crop_box: list[float] | None = Field(default=None, min_length=4, max_length=4)
    width: int | None = Field(default=None, strict=True, ge=1, le=8192)
    height: int | None = Field(default=None, strict=True, ge=1, le=8192)

    @model_validator(mode="after")
    def coherent(self) -> "RefinementPatch":
        self.classes = [name.strip() for name in self.classes]
        allowed = {"confidence": {"confidence"}, "add_classes": {"classes"},
                   "remove_classes": {"classes"}, "replace_classes": {"classes"},
                   "count_rule": {"count_threshold", "count_operator", "hold_s"},
                   "expected_text": {"expected_text", "match_mode"}, "sample_fps": {"fps"},
                   "eval_target": {"eval_target", "eval_metric"}, "crop": {"crop_box"},
                   "resize": {"width", "height"}}[self.kind]
        supplied = {key for key, value in self.model_dump().items()
                    if key not in {"kind", "scope", "block_id"} and value is not None and value != []}
        if not supplied or supplied - allowed:
            raise ValueError(f"{self.kind} requires only its supported change fields")
        if self.kind == "expected_text" and self.expected_text is None:
            raise ValueError("Text comparison requires explicitly requested expected text")
        if self.kind == "eval_target" and self.block_id is not None:
            raise ValueError("Evaluation targets apply to candidates, not individual blocks")
        if self.kind == "crop":
            if self.crop_box is None or not (0 <= self.crop_box[0] < self.crop_box[2] <= 1
                                             and 0 <= self.crop_box[1] < self.crop_box[3] <= 1):
                raise ValueError("Crop requires a normalized [x0, y0, x1, y1] rectangle with positive area")
        if self.kind == "resize" and (self.width is None or self.height is None):
            raise ValueError("Resize requires both explicit width and height in pixels")
        if any(not name or len(name) > 80 or any(ord(c) < 32 for c in name) for name in self.classes):
            raise ValueError("Classes must be nonempty names of at most 80 characters")
        if len({name.casefold() for name in self.classes}) != len(self.classes):
            raise ValueError("Classes must be unique")
        if self.eval_metric not in {None, "count_mae"} and self.eval_target is not None and self.eval_target > 1:
            raise ValueError("Accuracy targets must be in [0, 1]")
        return self

    def target_scope(self) -> Literal["selected", "all"]:
        return self.scope or ("selected" if self.kind == "confidence" else "all")


class RefinementBatch(Contract):
    patches: list[RefinementPatch] = Field(min_length=1, max_length=8)


class RefinementContext(Contract):
    candidates: list[PipelineSpec]
    selected_candidate_index: int
    current_goal: str
    conversation: list[dict[str, str]]
    classes: list[str]
    saved_zone_ids: list[str]
    clarification_count: int


class RefinementResult(Contract):
    preview: RunResult
    candidate_index: int
    message: str
    base_spec_hash: str
    spec_hash: str
    requires_review: bool = False
    affected_candidate_indices: list[int] = Field(default_factory=list)
    previewed_candidate_indices: list[int] = Field(default_factory=list)
    base_spec_hashes: dict[str, str] = Field(default_factory=dict)
    spec_hashes: dict[str, str] = Field(default_factory=dict)
