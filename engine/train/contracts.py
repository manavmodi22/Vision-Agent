"""Bounded training result. Completion never means deployment approval."""
from pydantic import Field

from spec.models import Contract


class TrainingResult(Contract):
    backend: str = "ssdlite320"
    base_model_id: str | None = None
    model_id: str
    model_path: str
    classes: list[str]
    epochs_completed: int = Field(ge=0)
    steps: int = Field(ge=1)
    elapsed_s: float = Field(ge=0)
    final_loss: float = Field(ge=0)
    training_samples: int
    evaluation_samples: int
    training_hash: str
    evaluation_hash: str
    device: str
    warnings: list[str]
