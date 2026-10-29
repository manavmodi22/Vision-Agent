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
    """The graph's single source. The host supplies selected media; no path or media ID belongs in a node reference. Its frame output has image type."""

    type: Literal["frame_sample"]
    fps: float = Field(gt=0, le=60)


class CropNode(Node):
    """Extract a static rectangular region before inference. The box is relative to this node's input image, not necessarily the original source. This does not locate objects dynamically."""

    type: Literal["crop"]
    image: Reference = Field(description="Reference to an image output of another node: $node_id.port.")
    box: tuple[float, float, float, float] = Field(description="Normalized [left, top, right, bottom] with positive area within [0,1].")

    @model_validator(mode="after")
    def rectangle(self) -> "CropNode":
        x0, y0, x1, y1 = self.box
        if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
            raise ValueError("A static crop needs normalized x0,y0,x1,y1 with positive area")
        return self


class ResizeNode(Node):
    """Resize an image to the given pixel dimensions before downstream inference."""

    type: Literal["resize"]
    image: Reference = Field(description="Reference to an image output of another node: $node_id.port.")
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class ModelNode(Node):
    image: Reference = Field(description="Reference to an image output of another graph node, never a media ID or filename. Use the upstream node's exact output port.")
    model_capability_id: str = Field(min_length=1, max_length=120)
    model_reason: str = Field(min_length=1, max_length=500)


class DetectNode(ModelNode):
    """Run the selected detector on the input image and return detections for the requested supported classes."""

    type: Literal["detect"]
    classes: list[Name] = Field(min_length=1, max_length=20)
    min_confidence: float = Field(ge=0, le=1)


class OCRNode(ModelNode):
    """Read all detected text in the input image. This node does not semantically select a requested field or discard unrelated text. Its text readings are included in preview output without requiring an event sink."""

    type: Literal["ocr"]


class BarcodeNode(ModelNode):
    """Decode supported machine-readable codes in the input image. Ordinary printed text requires a text reader. Decoded text is included in preview output without an event sink."""

    type: Literal["barcode"]


class ZoneNode(Node):
    """Filter detections using the project's already confirmed region geometry."""

    type: Literal["zone_filter"]
    dets: Reference = Field(description="Reference to a detections output: $node_id.dets.")
    zone_ids: list[Name] = Field(max_length=20)


class CountNode(Node):
    """Aggregate detections into counts by region; consumes the final zone-filtered detections when a zone filter is present."""

    type: Literal["count_per_zone"]
    dets: Reference = Field(description="Reference to a detections output: $node_id.dets.")
    include_unassigned: bool


class RuleNode(Node):
    """Test counts against a threshold and produce an event. Connect its event output to a sink_event node. Count-only applications do not need a rule."""

    type: Literal["rule"]
    counts: Reference = Field(description="Reference to a counts output: $node_id.counts.")
    operator: Literal[">=", "<=", ">", "<", "==", "!="]
    threshold: int = Field(ge=0, le=10000)
    hold_seconds: float = Field(ge=0, le=3600)


class MatchNode(Node):
    """Compare text readings with a fixed expected string and produce match events. This does not filter or replace the original text readings in preview output."""

    type: Literal["match"]
    text: Reference = Field(description="Reference to a text output: $node_id.text.")
    expected: str = Field(min_length=1, max_length=256)
    mode: Literal["contains", "exact"]
    emit: Literal["all", "matched", "mismatched"]


class EventNode(Node):
    """Receive an event produced by match or rule. Text is not an event. Optional for plain detection, counting or reading output; investigation previews never dispatch external events."""

    type: Literal["sink_event"]
    event: Reference = Field(description="Reference to an event output: $node_id.event; never a text, image or detections output.")


GraphNode = Annotated[SampleNode | CropNode | ResizeNode | DetectNode | OCRNode | BarcodeNode |
                      ZoneNode | CountNode | RuleNode | MatchNode | EventNode, Field(discriminator="type")]


class GraphCandidate(Contract):
    """One connected, acyclic vision graph. Output references must resolve to compatible ports on nodes in this graph. The host binds source media separately."""

    name: str = Field(min_length=1, max_length=120)
    nodes: list[GraphNode] = Field(min_length=2, max_length=16, description="Include exactly one frame_sample source and one to four detector/reader nodes. Connect each image operation to inference. References use $node_id.port and must match the source port's type. At most one detect, zone_filter, count_per_zone and rule node. An event sink is optional for plain reader/detection/count output.")
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
