"""Manifests for locally trained detectors; no executable model artifacts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from spec.models import Contract


class LocalDetectorManifest(Contract):
    id: str = Field(pattern=r"^local-[a-z0-9][a-z0-9_-]{0,70}$")
    backend: Literal["ssdlite320", "rtdetr-v2-r18"] = "ssdlite320"
    classes: list[str] = Field(min_length=1, max_length=64)
    code_license: Literal["BSD-3-Clause", "Apache-2.0"] = "BSD-3-Clause"
    weights_license: str = "Project dataset terms; local use only until reviewed for distribution"
    license: Literal["BSD-3-Clause architecture; project-trained weights", "Apache-2.0"] = "BSD-3-Clause architecture; project-trained weights"
    source: str = "https://github.com/pytorch/vision"
    training_hash: str
    evaluation_hash: str
    base_model_id: str | None = None
    created_at: str
    training_samples: int
    epochs_completed: int
    steps: int
    final_loss: float
    device: str = "cpu"
    base_weights_sha256: str | None = None
    training_seed: int | None = None
    upstream_model_id: str | None = None
    upstream_revision: str | None = None
    upstream_weights_sha256: str | None = None
    preserved_classes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # Registration provenance, never guessed from filenames, architecture or step counts.
    use_scope: Literal["user_candidate", "engineering_smoke", "unknown"] = "unknown"
    use_scope_evidence_ref: str | None = Field(default=None, max_length=300)
    initialization: Literal["pretrained_finetune", "random", "unknown"] = "unknown"
    training_state: Literal["untrained", "optimization_completed", "unknown"] = "unknown"


def local_model_path(model_id: str, model_root: Path) -> Path:
    if not re.fullmatch(r"local-[a-z0-9][a-z0-9_-]{0,70}", model_id):
        raise ValueError("Local model ID must start with local- and contain lowercase letters, digits, '_' or '-'")
    return model_root / model_id


def read_manifest(model_id: str, model_root: Path) -> LocalDetectorManifest:
    path = local_model_path(model_id, model_root) / "manifest.json"
    if not path.is_file():
        raise ValueError(f"No registered local model manifest for {model_id}")
    manifest = LocalDetectorManifest.model_validate_json(path.read_text())
    if manifest.id != model_id or manifest.backend not in {"ssdlite320", "rtdetr-v2-r18"}:
        raise ValueError(f"Invalid local model manifest: {model_id}")
    return manifest
