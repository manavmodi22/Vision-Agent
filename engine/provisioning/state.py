"""Stable install/runtime identities and content-bound smoke receipts."""
from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path

from engine.models.artifacts import canonical_hash, content_hash
from engine.models.manager import model_directory
from engine.provisioning.registry import Recipe, recipe_for
from engine.runtime_identity import source_identity
from spec.provisioning import ProvisioningHealth


def target_path(recipe: Recipe) -> Path:
    root = model_directory().resolve()
    path = root / recipe.model_id
    if path.is_symlink():
        raise ValueError("Installation targets cannot be symbolic links")
    return path


def runtime_snapshot(recipe: Recipe) -> dict[str, str]:
    result = {"runtime_source": source_identity(Path(__file__).resolve().parents[2]),
        "python": platform.python_version(), "system": platform.system(), "architecture": platform.machine(),
        "kernel": platform.release(), "kernel_build": platform.version(), "macos": platform.mac_ver()[0],
        "recipe": canonical_hash({"model_id": recipe.model_id, "revision": recipe.revision,
            "packages": recipe.packages, "platforms": recipe.platforms, "max_duration_s": recipe.max_duration_s,
            "artifacts": [item.model_dump(mode="json") for item in recipe.artifacts]})}
    for package in recipe.packages:
        try:
            result["package:" + package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result["package:" + package] = "missing"
    return result


def installation_hash(recipe: Recipe) -> str | None:
    target = target_path(recipe)
    if not target.exists():
        return None
    if not target.is_dir():
        raise ValueError("Installation target is not a directory; existing content was preserved")
    entries = list(target.iterdir())
    if len(entries) > 128 or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError("Installation contains unsupported nested or linked files; existing content was preserved")
    if sum(entry.stat().st_size for entry in entries) > 4 * 1024**3:
        raise ValueError("Installation exceeds the reviewed artifact size bound")
    return canonical_hash({entry.name: content_hash(entry) for entry in sorted(entries)})


def installation_matches(recipe: Recipe) -> bool:
    target = target_path(recipe)
    return all((target / item.filename).is_file() and not (target / item.filename).is_symlink()
        and (target / item.filename).stat().st_size == item.expected_bytes
        and content_hash(target / item.filename) == item.expected_sha256 for item in recipe.artifacts)


def health_path(model_id: str) -> Path:
    recipe_for(model_id)
    return model_directory().resolve() / ".provisioning-health" / f"{model_id}.json"


def current_health(model_id: str) -> ProvisioningHealth | None:
    try:
        recipe = recipe_for(model_id)
        path = health_path(model_id)
        if not path.is_file() or path.stat().st_size > 65536:
            return None
        receipt = ProvisioningHealth.model_validate_json(path.read_text())
        if (receipt.model_id != model_id or not installation_matches(recipe)
                or receipt.installation_hash != installation_hash(recipe)
                or receipt.runtime_snapshot != runtime_snapshot(recipe)):
            return None
        from engine.adapters.contracts import DetectionRequest
        from engine.adapters.identity import resolve_execution_identity
        identity = resolve_execution_identity(DetectionRequest(model_id=model_id, classes=["person"], min_conf=.3))
        if receipt.execution_identity_hash != identity.identity_hash or identity.unavailable_artifacts:
            return None
        return receipt
    except (OSError, ValueError):
        return None
