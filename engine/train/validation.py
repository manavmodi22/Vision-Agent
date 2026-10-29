"""Data separation checks performed before constructing a training model."""
from pathlib import Path

from engine.eval.configuration import _read_configuration, connected_group, project_dataset
from engine.eval.hashes import file_hash
from engine.evidence_metadata import pixel_hash, relative_image, unique_images
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
    for subset in (training, evaluation):
        unique_images(project_root, [row.image_path for row in subset.annotations])
    training_pixels = {pixel_hash(project_root / row.image_path) for row in training.annotations}
    evaluation_pixels = {pixel_hash(project_root / row.image_path) for row in evaluation.annotations}
    if training_pixels & evaluation_pixels:
        raise ValueError("Training/evaluation leakage: decoded pixels appear in both splits, including re-encoded copies")
    combined = EvalDataset(id="training-validation", annotations=[*training.annotations, *evaluation.annotations])
    existing = project_dataset(project_root)
    all_rows = {relative_image(project_root, row.image_path): row for row in [*existing.annotations, *combined.annotations]}
    config = _read_configuration(project_root, EvalDataset(id=combined.id, annotations=list(all_rows.values())))
    train_paths = {relative_image(project_root, row.image_path) for row in training.annotations}
    eval_paths = {relative_image(project_root, row.image_path) for row in evaluation.annotations}
    used = train_paths | eval_paths
    for row in config.images:
        if row.image_path in used and any(other.split == "acceptance" for other in connected_group(row, config.images)):
            raise ValueError("Reserved acceptance groups cannot be used for training or iterative model selection")
        if row.image_path in train_paths and any(other.image_path in eval_paths for other in connected_group(row, config.images)):
            raise ValueError("Training/evaluation leakage: known scene or original source asset crosses the split")
    classes = sorted({d.label for item in training.annotations for d in item.detections})
    if not classes:
        raise ValueError("Training requires at least one labeled positive object")
    evaluation_classes = {d.label for item in evaluation.annotations for d in item.detections}
    if evaluation_classes - set(classes):
        raise ValueError("Every evaluation class must have reviewed examples in the training split")
    return classes
