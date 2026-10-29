"""Data separation checks performed before constructing a training model."""
from pathlib import Path

from engine.eval.hashes import file_hash
from spec.models import EvalDataset


def validate_training_data(training: EvalDataset, evaluation: EvalDataset, project_root: Path) -> list[str]:
    if len(training.annotations) < 2 or not evaluation.annotations:
        raise ValueError("Training needs at least 2 reviewed training images and a separate nonempty evaluation set")
    if any(not item.reviewed for dataset in (training, evaluation) for item in dataset.annotations):
        raise ValueError("Training and evaluation images must all be reviewed")
    if (project_root / "synthetic-provenance.json").exists() or any(
        dataset.id == "synthetic-lanes-v1" for dataset in (training, evaluation)):
        raise ValueError("The colored-rectangle demo fixtures cannot be used to train a warehouse detector")
    training_hashes = {file_hash((project_root / item.image_path).resolve()) for item in training.annotations}
    evaluation_hashes = {file_hash((project_root / item.image_path).resolve()) for item in evaluation.annotations}
    if len(training_hashes) != len(training.annotations) or len(evaluation_hashes) != len(evaluation.annotations):
        raise ValueError("Each split must contain unique image content, not duplicate files")
    if training_hashes & evaluation_hashes:
        raise ValueError("Training/evaluation leakage: an image appears in both splits, including renamed copies")
    classes = sorted({d.label for item in training.annotations for d in item.detections})
    if not classes:
        raise ValueError("Training requires at least one labeled positive object")
    evaluation_classes = {d.label for item in evaluation.annotations for d in item.detections}
    if evaluation_classes - set(classes):
        raise ValueError("Every evaluation class must have reviewed examples in the training split")
    return classes
