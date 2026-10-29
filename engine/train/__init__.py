"""Genuine bounded local training; model promotion remains a separate eval gate."""
from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PIL import Image, ImageOps

from engine.eval.hashes import dataset_hash
from engine.models.local_manifest import LocalDetectorManifest, local_model_path, read_manifest
from engine.models.manager import model_directory
from engine.models.ssdlite import image_tensor, make_model
from engine.train.contracts import TrainingResult
from engine.train.validation import validate_training_data
from spec.models import Annotation, EvalDataset

if TYPE_CHECKING:
    import torch


def _sample(annotation: Annotation, root: Path, classes: list[str]) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    import torch
    with Image.open(root / annotation.image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    boxes = [[d.box[i] * (image.width if i % 2 == 0 else image.height) for i in range(4)]
             for d in annotation.detections]
    target = {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
              "labels": torch.tensor([classes.index(d.label) + 1 for d in annotation.detections], dtype=torch.int64)}
    return image_tensor(image), target


def _train_ssdlite(training: EvalDataset, evaluation: EvalDataset, project_root: Path,
                   model_id: str, max_minutes: float = 5, epochs: int = 1, *,
                   base_model_id: str | None = None) -> TrainingResult:
    """Train SSDLite from scratch or fine-tune local weights; never train on holdout."""
    import torch
    from safetensors.torch import load_file, save_file

    if not 0 < max_minutes <= 60 or not 1 <= epochs <= 100:
        raise ValueError("Training budgets must be 0 < minutes <= 60 and 1 <= epochs <= 100")
    if len(training.annotations) > 1000:
        raise ValueError("The local trainer is limited to 1000 reviewed training images per job")
    classes = validate_training_data(training, evaluation, project_root)
    model_root = model_directory()
    model_root.mkdir(parents=True, exist_ok=True)
    target_path = local_model_path(model_id, model_root)
    if target_path.exists():
        raise ValueError("The model ID already exists; use a new version so evaluation history remains reproducible")
    training_fingerprint = dataset_hash(training, project_root)
    evaluation_fingerprint = dataset_hash(evaluation, project_root)
    started = time.monotonic()
    model = make_model(len(classes) + 1)
    if base_model_id:
        base = read_manifest(base_model_id, model_root)
        if base.classes != classes:
            raise ValueError("Fine-tuning requires the same class list as the selected local model")
        model.load_state_dict(load_file(str(model_root / base_model_id / "model.safetensors")), strict=True)
    model.train()
    # Tiny user batches otherwise fail on 1x1 feature maps. Frozen running stats
    # preserve consistent normalization while convolution/head weights still learn.
    for module in model.modules():
        if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
            module.eval()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.002, momentum=0.9, weight_decay=0.0005)
    steps = completed = 0
    final_loss = 0.0
    exhausted = False
    for _ in range(epochs):
        for offset in range(0, len(training.annotations), 2):
            if time.monotonic() - started >= max_minutes * 60:
                exhausted = True
                break
            batch = [_sample(item, project_root, classes) for item in training.annotations[offset:offset + 2]]
            images, targets = zip(*batch, strict=True)
            losses = cast("dict[str, torch.Tensor]", model(list(images), list(targets)))
            loss = torch.stack(list(losses.values())).sum()
            if not bool(torch.isfinite(loss)):
                raise ValueError("Training produced a non-finite loss; no model was registered")
            optimizer.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            optimizer.step()
            steps += 1
            final_loss = float(loss.detach())
        if exhausted:
            break
        completed += 1
    if steps == 0:
        raise ValueError("Training time budget expired before the first optimizer step")
    if dataset_hash(training, project_root) != training_fingerprint or dataset_hash(evaluation, project_root) != evaluation_fingerprint:
        raise ValueError("Labels or images changed while training; no model was registered")
    warnings = [
        "Optimization completed; this model has not passed held-out evaluation or deployment approval.",
        "Disjoint image contents were verified; independence of scenes, cameras and time periods was not.",
        "Architecture code is BSD-3-Clause; trained weights retain project dataset conditions.",
    ]
    if not base_model_id:
        warnings.append("Initialized from scratch; a small training set is unlikely to produce a useful detector.")
    if exhausted:
        warnings.append("Time budget reached between optimizer steps; the final epoch is incomplete.")
    manifest = LocalDetectorManifest(id=model_id, classes=classes, training_hash=training_fingerprint,
        evaluation_hash=evaluation_fingerprint, base_model_id=base_model_id,
        created_at=datetime.now(UTC).isoformat(), training_samples=len(training.annotations),
        epochs_completed=completed, steps=steps, final_loss=final_loss, warnings=warnings)
    with tempfile.TemporaryDirectory(prefix=f".{model_id}-", dir=model_root) as directory:
        temporary = Path(directory)
        save_file({name: value.detach().cpu().contiguous() for name, value in model.state_dict().items()},
                  str(temporary / "model.safetensors"))
        (temporary / "manifest.json").write_text(manifest.model_dump_json(indent=2))
        os.rename(temporary, target_path)
    return TrainingResult(model_id=model_id, model_path=str(target_path), classes=classes,
        epochs_completed=completed, steps=steps, elapsed_s=time.monotonic() - started,
        final_loss=final_loss, training_samples=len(training.annotations),
        evaluation_samples=len(evaluation.annotations), training_hash=training_fingerprint,
        evaluation_hash=evaluation_fingerprint, device="cpu", warnings=warnings,
        base_model_id=base_model_id)


def train_detector(training: EvalDataset, evaluation: EvalDataset, project_root: Path,
                   model_id: str, max_minutes: float = 5, epochs: int = 10, *,
                   base_model_id: str | None = None) -> TrainingResult:
    """Specialize pretrained RT-DETRv2 by default, or resume an existing local model."""
    if base_model_id and base_model_id.startswith("local-"):
        manifest = read_manifest(base_model_id, model_directory())
        if manifest.backend == "ssdlite320":
            return _train_ssdlite(training, evaluation, project_root, model_id, max_minutes,
                                  epochs, base_model_id=base_model_id)
    elif base_model_id not in {None, "rtdetr-v2-r18"}:
        raise ValueError("Choose the pretrained RT-DETRv2 base or an existing local detector")
    from engine.train.rtdetr import train_rtdetr
    return train_rtdetr(training, evaluation, project_root, model_id, max_minutes, epochs, base_model_id)


__all__ = ["train_detector", "TrainingResult", "validate_training_data"]
