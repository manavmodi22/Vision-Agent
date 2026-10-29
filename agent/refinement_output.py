"""Compact per-kind model schema; engine patches remain the shared contract."""
from typing import Annotated, Literal

from pydantic import Field

from agent.refinement_contracts import RefinementDecision
from spec.models import Contract
from spec.refinement import RefinementPatch


class Target(Contract):
    scope: Literal["selected", "all"] | None = None
    block_id: str | None = None


class Confidence(Target):
    kind: Literal["confidence"]
    confidence: float = Field(ge=0, le=1)


class AddClasses(Target):
    kind: Literal["add_classes"]
    classes: list[str] = Field(min_length=1, max_length=64)


class RemoveClasses(Target):
    kind: Literal["remove_classes"]
    classes: list[str] = Field(min_length=1, max_length=64)


class ReplaceClasses(Target):
    kind: Literal["replace_classes"]
    classes: list[str] = Field(min_length=1, max_length=64)


class CountRule(Target):
    kind: Literal["count_rule"]
    count_threshold: float | None = Field(default=None, ge=0, le=1_000_000_000)
    count_operator: Literal[">=", "<=", "==", "!=", ">", "<"] | None = None
    hold_s: float | None = Field(default=None, ge=0, le=86400)


class ExpectedText(Target):
    kind: Literal["expected_text"]
    expected_text: str = Field(min_length=1, max_length=256)
    match_mode: Literal["exact", "contains"] | None = None


class SampleFPS(Target):
    kind: Literal["sample_fps"]
    fps: float = Field(gt=0, le=60)


class EvalTarget(Contract):
    kind: Literal["eval_target"]
    scope: Literal["selected", "all"] | None = None
    eval_metric: Literal["count_mae", "precision", "recall", "text_accuracy"] | None = None
    eval_target: float | None = Field(default=None, ge=0)


class Crop(Target):
    kind: Literal["crop"]
    crop_box: list[float] = Field(min_length=4, max_length=4)


class Resize(Target):
    kind: Literal["resize"]
    width: int = Field(strict=True, ge=1, le=8192)
    height: int = Field(strict=True, ge=1, le=8192)


ModelPatch = Annotated[Confidence | AddClasses | RemoveClasses | ReplaceClasses | CountRule | ExpectedText | SampleFPS | EvalTarget | Crop | Resize,
                       Field(discriminator="kind")]


class RefinementModelDecision(Contract):
    message: str = Field(min_length=1, max_length=1000)
    questions: list[str] = Field(max_length=3)
    patches: list[ModelPatch] = Field(max_length=8)

    def normalized(self) -> RefinementDecision:
        return RefinementDecision(message=self.message, questions=self.questions,
            patches=[RefinementPatch.model_validate(patch.model_dump(mode="json")) for patch in self.patches])
