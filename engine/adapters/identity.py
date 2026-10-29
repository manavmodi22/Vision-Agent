"""Resolve implemented adapters without downloading or substituting models."""
from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path

from engine.adapters.contracts import DetectionRequest, InferenceRequest
from engine.blocks.reading_identity import native_reading_identity
from engine.models.artifacts import canonical_hash, content_hash, model_artifacts
from engine.models.manager import ModelUnavailable, model_directory
from spec.inference import ExecutionIdentity

_CODE_BASELINES: dict[str, str] = {}


def adapter_id(model_id: str) -> str:
    if model_id in {"fixture-color-v1", "owlv2-base-patch16", "rtdetr-v2-r18", "apple-vision"}:
        return "owlv2" if model_id == "owlv2-base-patch16" else model_id
    if model_id.startswith("local-"):
        from engine.models.local_manifest import local_model_path, read_manifest
        path = local_model_path(model_id, model_directory())
        return read_manifest(model_id, model_directory()).backend if (path / "manifest.json").is_file() else "local-unavailable"
    raise ModelUnavailable(f"No implemented adapter for '{model_id}'")


def execution_provider(adapter: str) -> str:
    if adapter == "apple-vision":
        return "apple-vision-system"
    if adapter in {"owlv2", "rtdetr-v2-r18"}:
        try:
            import torch
        except ImportError:
            # Missing runtime remains describable for saved/offline authoring.
            # Executing still fails in validate_model; no replacement is selected.
            return "unavailable"
        return "mps" if torch.backends.mps.is_available() else "cpu"
    return "cpu"


def _code_hash(adapter: str) -> str:
    root = Path(__file__).resolve().parents[2]
    files = ["engine/adapters/contracts.py", "engine/adapters/identity.py", "engine/adapters/legacy.py",
             "engine/adapters/registry.py", "engine/models/artifacts.py", "spec/inference.py"]
    if adapter == "apple-vision":
        files.extend(["engine/blocks/reading.py", "engine/blocks/reading_identity.py"])
    else:
        files.extend(["engine/models/__init__.py", "engine/models/manager.py"])
        name = {"fixture-color-v1": "fixture", "owlv2": "owlv2", "rtdetr-v2-r18": "rtdetr",
                "ssdlite320": "ssdlite", "local-unavailable": "local_manifest"}[adapter]
        files.append(f"engine/models/{name}.py")
        if adapter in {"ssdlite320", "rtdetr-v2-r18"}:
            files.append("engine/models/local_manifest.py")
    current = canonical_hash({name: content_hash(root / name) for name in files})
    baseline = _CODE_BASELINES.setdefault(adapter, current)
    if baseline != current:
        raise ModelUnavailable("Adapter source changed after this process began using it; restart the engine")
    return current


def _runtime_hash(adapter: str) -> str:
    names = ["pillow", "pydantic"]
    if adapter == "fixture-color-v1":
        names.append("numpy")
    elif adapter in {"owlv2", "rtdetr-v2-r18"}:
        names.extend(["torch", "transformers", "numpy", "scipy", "safetensors", "tokenizers"])
    elif adapter == "ssdlite320":
        names.extend(["torch", "torchvision", "numpy", "safetensors"])
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    # Version metadata is a runtime description, not a hash of Apple's hidden weights.
    return canonical_hash({"python": platform.python_version(), "packages": versions})


def resolve_execution_identity(request: InferenceRequest) -> ExecutionIdentity:
    adapter = adapter_id(request.model_id)
    if isinstance(request, DetectionRequest) and adapter == "apple-vision":
        raise ModelUnavailable("Apple Vision is a reader, not a detection adapter")
    system = {"architecture": platform.machine()}
    missing: list[str] = []
    scope = "local_artifacts_verified"
    if adapter == "apple-vision":
        native = native_reading_identity()
        bridge = str(native.pop("bridge_sha256"))
        hashes = {"native_bridge": bridge} if bridge != "missing" else {}
        missing = [] if hashes else ["native_bridge"]
        system.update({key: str(value) for key, value in native.items()})
        scope = "system_framework_versioned"
    elif adapter == "fixture-color-v1":
        hashes = {"fixture.py": content_hash(Path(__file__).parents[1] / "models/fixture.py")}
        scope = "synthetic_code"
    else:
        hashes, missing = model_artifacts(request.model_id)
        system.update({"os": platform.system(), "kernel": platform.release(),
                       "kernel_build": platform.version(), "macos": platform.mac_ver()[0]})
    payload = {
        "capability_id": "model." + request.model_id, "model_id": request.model_id,
        "adapter_id": adapter, "identity_scope": scope, "artifact_hashes": hashes,
        "unavailable_artifacts": missing, "adapter_code_sha256": _code_hash(adapter),
        "runtime_manifest_sha256": _runtime_hash(adapter), "system_identity": system,
        "provider": execution_provider(adapter), "config_sha256": canonical_hash(request.model_dump(mode="json")),
    }
    return ExecutionIdentity.model_validate({**payload, "identity_hash": canonical_hash(payload)})
