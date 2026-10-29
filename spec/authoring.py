"""Typed composition data; imported paths and execution authority are host-owned."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from spec.models import Contract

Reference = Annotated[str, Field(pattern=r"^\$[A-Za-z][A-Za-z0-9_-]*\.[A-Za-z][A-Za-z0-9_]*$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Name = Annotated[str, Field(min_length=1, max_length=80)]


class Node(Contract):
    # Constrained decoders can enforce schema property order. Emit the
    # discriminator before shared fields so every node variant remains selectable.
    type: str
    id: Identifier


class SampleNode(Node):
    type: Literal["frame_sample"]
    fps: float = Field(gt=0, le=60)


class CropNode(Node):
    type: Literal["crop"]
    image: Reference
    box: tuple[float, float, float, float]

    @model_validator(mode="after")
    def rectangle(self) -> "CropNode":
        x0, y0, x1, y1 = self.box
        if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
            raise ValueError("A static crop needs normalized x0,y0,x1,y1 with positive area")
        return self


class ResizeNode(Node):
    type: Literal["resize"]
    image: Reference
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class ModelNode(Node):
    image: Reference
    model_capability_id: str = Field(min_length=1, max_length=120)
    model_reason: str = Field(min_length=1, max_length=500)


class DetectNode(ModelNode):
    type: Literal["detect"]
    classes: list[Name] = Field(min_length=1, max_length=20)
    min_confidence: float = Field(ge=0, le=1)


class OCRNode(ModelNode):
    type: Literal["ocr"]


class BarcodeNode(ModelNode):
    type: Literal["barcode"]


class ZoneNode(Node):
    type: Literal["zone_filter"]
    dets: Reference
    zone_ids: list[Name] = Field(max_length=20)


class CountNode(Node):
    type: Literal["count_per_zone"]
    dets: Reference
    include_unassigned: bool


class RuleNode(Node):
    type: Literal["rule"]
    counts: Reference
    operator: Literal[">=", "<=", ">", "<", "==", "!="]
    threshold: int = Field(ge=0, le=10000)
    hold_seconds: float = Field(ge=0, le=3600)


class MatchNode(Node):
    type: Literal["match"]
    text: Reference
    expected: str = Field(min_length=1, max_length=256)
    mode: Literal["contains", "exact"]
    emit: Literal["all", "matched", "mismatched"]


class EventNode(Node):
    type: Literal["sink_event"]
    event: Reference


GraphNode = Annotated[SampleNode | CropNode | ResizeNode | DetectNode | OCRNode | BarcodeNode |
                      ZoneNode | CountNode | RuleNode | MatchNode | EventNode, Field(discriminator="type")]


class GraphCandidate(Contract):
    name: str = Field(min_length=1, max_length=120)
    nodes: list[GraphNode] = Field(min_length=2, max_length=16)
    metric: Literal["count_mae", "precision", "recall", "text_accuracy"]
    target: float = Field(ge=0)

    @model_validator(mode="after")
    def identifiers_and_metric(self) -> "GraphCandidate":
        identifiers = [node.id for node in self.nodes]
        if "inputs" in identifiers or len(set(identifiers)) != len(identifiers):
            raise ValueError("Node IDs must be unique; inputs is reserved")
        if self.metric != "count_mae" and self.target > 1:
            raise ValueError("Ratio metric targets must be between zero and one")
        return self


class GraphPlanDecision(Contract):
    schema_version: Literal["0.2"]
    message: str = Field(min_length=1, max_length=2000)
    questions: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(max_length=3)
    graphs: list[GraphCandidate] = Field(max_length=3)

    @model_validator(mode="after")
    def one_outcome(self) -> "GraphPlanDecision":
        if bool(self.questions) == bool(self.graphs):
            raise ValueError("Ask essential questions or propose one to three graphs, never both or neither")
        if any(not value.strip() for value in self.questions):
            raise ValueError("Questions cannot be blank")
        return self
