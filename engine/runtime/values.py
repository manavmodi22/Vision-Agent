"""Internal typed values crossing graph ports."""
from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image
from pydantic import JsonValue

from spec.inference import BlockInference
from spec.models import Detection, JudgementEvidence


@dataclass
class ImageValue:
    image: Image.Image
    # Offset and scale map local normalized coordinates back to the original frame.
    transform: tuple[float, float, float, float] = (0, 0, 1, 1)


@dataclass
class DetectionsValue:
    detections: list[Detection]
    zones: list[str] = field(default_factory=list)
    inference: BlockInference | None = None


@dataclass
class CountsValue:
    counts: dict[str, int]


@dataclass
class TextValue:
    texts: list[str]
    inference: BlockInference | None = None


@dataclass
class EventValue:
    events: list[dict[str, JsonValue]]


@dataclass
class JudgementValue:
    judgement: JudgementEvidence


type PortValue = ImageValue | DetectionsValue | CountsValue | TextValue | EventValue | JudgementValue


@dataclass
class ExecutionState:
    true_since: dict[tuple[str, str], float] = field(default_factory=dict)
