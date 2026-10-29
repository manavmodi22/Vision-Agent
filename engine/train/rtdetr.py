"""Custom-class specialization of a pinned permissive pretrained detector."""
from __future__ import annotations

import math
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PIL import Image, ImageOps

from engine.eval.hashes import dataset_hash, file_hash
from engine.models.local_manifest import LocalDetectorManifest, local_model_path, read_manifest
from engine.models.manager import model_directory, rtdetr_path, validate_model
from engine.train.contracts import TrainingResult
from engine.train.validation import validate_training_data
from spec.models import Annotation, EvalDataset

if TYPE_CHECKING:
    import torch
    from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection


def _checkpoint_path(base_model_id: str | None) -> Path:
    if base_model_id and base_model_id.startswith("local-"):
        manifest = read_manifest(base_model_id, model_directory())
        if manifest.backend != "rtdetr-v2-r18":
            raise ValueError("The selected checkpoint is not an RT-DETRv2 detector")
        return model_directory() / base_model_id
    validate_model("rtdetr-v2-r18")
    return rtdetr_path()


def _checkpoint_hashes(path: Path) -> dict[str, str]:
    names = ["model.safetensors", "config.json", "preprocessor_config.json"]
    names += [name for name in ("manifest.json", "VISIONAPP_REVISION.txt") if (path / name).is_file()]
    return {name: file_hash(path / name) for name in names}


def prepare_model(classes: list[str], base_model_id: str | None) -> tuple[RTDetrImageProcessor, RTDetrV2ForObjectDetection, list[str], Path]:
    from transformers import RTDetrImageProcessor, RTDetrV2ForObjectDetection
    path = _checkpoint_path(base_model_id)
    pretrained = RTDetrV2ForObjectDetection.from_pretrained(path, local_files_only=True, use_safetensors=True)
    config = type(pretrained.config).from_dict(pretrained.config.to_dict())
    config.num_labels = len(classes)
    config.id2label = dict(enumerate(classes))
    config.label2id = {name: index for index, name in enumerate(classes)}
    config.disable_custom_kernels = True
    model = RTDetrV2ForObjectDetection(config)
    source, target = pretrained.state_dict(), model.state_dict()
    source_classes = {name.casefold(): index for index, name in pretrained.config.id2label.items()}
    preserved = _transfer_parameters(source, target, source_classes, classes)
    model.load_state_dict(target, strict=True)
    processor = RTDetrImageProcessor.from_pretrained(path, local_files_only=True)
    return processor, model, preserved, path


def _transfer_parameters(source: dict[str, torch.Tensor], target: dict[str, torch.Tensor],
                         source_classes: dict[str, int], classes: list[str]) -> list[str]:
    """Preserve compatible learned features and class rows; unseen classes start rare."""
    preserved = [name for name in classes if name.casefold() in source_classes]
    for key, value in target.items():
        if key not in source:
            continue
        if any(part in key for part in ("class_embed", "score_head")):
            for index, label in enumerate(classes):
                if label.casefold() in source_classes:
                    value[index].copy_(source[key][source_classes[label.casefold()]])
                elif key.endswith(".bias"):
                    # A 0.5 prior on every unmatched query overwhelms a small custom set.
                    value[index].fill_(math.log(0.01 / 0.99))
            if "denoising_class_embed" in key:
                value[-1].copy_(source[key][-1])
        elif value.shape == source[key].shape:
            value.copy_(source[key])
    return preserved


def _batch(annotations: list[Annotation], root: Path, classes: list[str],
           processor: RTDetrImageProcessor, device: str) -> tuple[torch.Tensor, list[dict[str, torch.Tensor]]]:
    images: list[Image.Image] = []
    targets = []
    for index, annotation in enumerate(annotations):
        with Image.open(root / annotation.image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        images.append(image)
        objects = []
        for detection in annotation.detections:
            x0, y0, x1, y1 = detection.box
            box = [x0 * image.width, y0 * image.height, (x1 - x0) * image.width, (y1 - y0) * image.height]
            objects.append({"bbox": box, "area": box[2] * box[3], "category_id": classes.index(detection.label), "iscrowd": 0})
        targets.append({"image_id": index, "annotations": objects})
    batch = processor(images=images, annotations=targets, return_tensors="pt")
    pixels = cast("torch.Tensor", batch["pixel_values"]).to(device)
    labels = [{key: value.to(device) for key, value in item.items()} for item in batch["labels"]]
    return pixels, labels


def train_rtdetr(training: EvalDataset, evaluation: EvalDataset, project_root: Path,
                 model_id: str, max_minutes: float, epochs: int, base_model_id: str | None) -> TrainingResult:
    import torch
    if not 0 < max_minutes <= 60 or not 1 <= epochs <= 100:
        raise ValueError("Training budgets must be 0 < minutes <= 60 and 1 <= epochs <= 100")
    if len(training.annotations) > 1000:
        raise ValueError("Local training is limited to 1000 reviewed images per job")
    classes = validate_training_data(training, evaluation, project_root)
    model_root = model_directory()
    model_root.mkdir(parents=True, exist_ok=True)
    target_path = local_model_path(model_id, model_root)
    if target_path.exists():
        raise ValueError("The model ID already exists; create a new model version")
    training_hash = dataset_hash(training, project_root)
    evaluation_hash = dataset_hash(evaluation, project_root)
    started = time.monotonic()
    torch.manual_seed(0)
    source_fingerprint = _checkpoint_hashes(_checkpoint_path(base_model_id))
    processor, model, preserved, base_path = prepare_model(classes, base_model_id)
    if _checkpoint_hashes(base_path) != source_fingerprint:
        raise ValueError("Source checkpoint changed while loading; training discarded")
    base_hash = source_fingerprint["model.safetensors"]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device).train()  # type: ignore[arg-type]  # Transformers device-move decorator has an incorrect stub.
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=1e-4)
    steps = completed = 0
    final_loss = 0.0
    exhausted = False
    for _ in range(epochs):
        for offset in range(0, len(training.annotations), 2):
            if time.monotonic() - started >= max_minutes * 60:
                exhausted = True
                break
            pixels, labels = _batch(training.annotations[offset:offset + 2], project_root, classes, processor, device)
            output = model(pixel_values=pixels, labels=labels)
            loss = cast("torch.Tensor", output.loss)
            if not bool(torch.isfinite(loss)):
                raise ValueError("RT-DETRv2 training produced a non-finite loss; no checkpoint registered")
            optimizer.zero_grad()
            loss.backward()  # type: ignore[no-untyped-call]
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            steps += 1
            final_loss = float(loss.detach().cpu())
        if exhausted:
            break
        completed += 1
    if steps == 0:
        raise ValueError("Training budget expired before an optimizer step completed")
    if (dataset_hash(training, project_root) != training_hash or dataset_hash(evaluation, project_root) != evaluation_hash
            or _checkpoint_hashes(base_path) != source_fingerprint):
        raise ValueError("Labels, images or source checkpoint changed during training; result discarded")
    warnings = ["Pretrained detector specialized locally; held-out scoring and user deployment approval are still required.",
                "Image-content separation is verified; camera/scene/time independence must be checked separately."]
    if exhausted:
        warnings.append("Time budget reached between optimizer steps; final epoch is incomplete.")
    revision_path = rtdetr_path() / "VISIONAPP_REVISION.txt"
    revision = revision_path.read_text().strip() if revision_path.exists() else None
    upstream_hash: str | None = base_hash
    if base_model_id and base_model_id.startswith("local-"):
        lineage = read_manifest(base_model_id, model_root)
        revision = lineage.upstream_revision
        upstream_hash = lineage.upstream_weights_sha256
    manifest = LocalDetectorManifest(id=model_id, backend="rtdetr-v2-r18", classes=classes,
        code_license="Apache-2.0", license="Apache-2.0",
        weights_license="Apache-2.0 upstream checkpoint; local fine-tune also subject to project dataset terms",
        source="https://huggingface.co/PekingU/rtdetr_v2_r18vd", training_hash=training_hash,
        evaluation_hash=evaluation_hash, base_model_id=base_model_id or "rtdetr-v2-r18",
        created_at=datetime.now(UTC).isoformat(), training_samples=len(training.annotations),
        epochs_completed=completed, steps=steps, final_loss=final_loss, device=device, warnings=warnings,
        upstream_model_id="PekingU/rtdetr_v2_r18vd", upstream_revision=revision,
        upstream_weights_sha256=upstream_hash, base_weights_sha256=base_hash, training_seed=0, preserved_classes=preserved)
    with tempfile.TemporaryDirectory(prefix=f".{model_id}-", dir=model_root) as directory:
        temporary = Path(directory)
        model.cpu().save_pretrained(temporary, safe_serialization=True)
        processor.save_pretrained(temporary)
        (temporary / "manifest.json").write_text(manifest.model_dump_json(indent=2))
        os.rename(temporary, target_path)
    if device == "mps":
        del model, optimizer
        torch.mps.empty_cache()
    return TrainingResult(model_id=model_id, model_path=str(target_path), classes=classes,
        epochs_completed=completed, steps=steps, elapsed_s=time.monotonic() - started, final_loss=final_loss,
        training_samples=len(training.annotations), evaluation_samples=len(evaluation.annotations),
        training_hash=training_hash, evaluation_hash=evaluation_hash, device=device, warnings=warnings,
        backend="rtdetr-v2-r18", base_model_id=base_model_id or "rtdetr-v2-r18")
