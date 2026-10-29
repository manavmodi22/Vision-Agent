"""Explicit local model availability and license policy; no automatic downloads."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from pydantic import JsonValue


class ModelUnavailable(ValueError):
    """The requested model cannot execute on this installation."""


def model_directory() -> Path:
    return Path(os.environ.get("VISION_MODELS_DIR", str(
        Path.home() / "Library/Application Support/VisionApp/models"))).expanduser()


def owlv2_path() -> Path:
    return model_directory() / "owlv2-base-patch16"


def rtdetr_path() -> Path:
    return model_directory() / "rtdetr-v2-r18"


def list_models() -> list[dict[str, JsonValue]]:
    path = owlv2_path()
    available = (path / "config.json").is_file() and (path / "model.safetensors").is_file()
    available = available and importlib.util.find_spec("transformers") is not None
    available = available and importlib.util.find_spec("torch") is not None
    available = available and importlib.util.find_spec("scipy") is not None
    records: list[dict[str, JsonValue]] = [
        {"id": "fixture-color-v1", "name": "Synthetic color fixture", "license": "MIT",
         "available": True, "synthetic": True, "backend": "numpy",
         "description": "Test rectangles only; not a warehouse detector.", "estimated_fps": None},
        {"id": "owlv2-base-patch16", "name": "OWLv2 base patch16 ensemble", "license": "Apache-2.0",
         "available": available, "synthetic": False, "backend": "transformers",
         "path": str(path), "source": "https://huggingface.co/google/owlv2-base-patch16-ensemble",
         "description": "Open-vocabulary detector; install weights locally before use.",
         "estimated_fps": None},
        {"id": "apple-vision", "name": "Apple Vision OCR and barcode", "license": "macOS system framework",
         "available": bool(os.environ.get("VISION_APP_BINARY")) and Path(os.environ.get("VISION_APP_BINARY", "")).is_file(), "synthetic": False,
         "backend": "apple-vision", "description": "Native macOS OCR and barcode bridge.",
         "estimated_fps": None},
    ]
    rtdetr = rtdetr_path()
    rtdetr_available = ((rtdetr / "model.safetensors").is_file() and (rtdetr / "config.json").is_file()
                        and (rtdetr / "preprocessor_config.json").is_file()
                        and importlib.util.find_spec("transformers") is not None
                        and importlib.util.find_spec("torch") is not None)
    try:
        rtdetr_classes = trained_classes("rtdetr-v2-r18") or []
    except (OSError, ValueError):
        rtdetr_available, rtdetr_classes = False, []
    records.append({"id": "rtdetr-v2-r18", "name": "RT-DETRv2 R18 pretrained", "license": "Apache-2.0",
        "available": rtdetr_available, "synthetic": False, "backend": "rtdetr-v2-r18", "path": str(rtdetr),
        "source": "https://huggingface.co/PekingU/rtdetr_v2_r18vd", "classes": list(rtdetr_classes),
        "description": "COCO-pretrained detector and default base for custom-class fine-tuning.", "estimated_fps": None})
    from engine.models.local_manifest import read_manifest
    for manifest_path in sorted(model_directory().glob("local-*/manifest.json")):
        model_id = manifest_path.parent.name
        try:
            manifest = read_manifest(model_id, model_directory())
            available = ((manifest_path.parent / "model.safetensors").is_file()
                         and importlib.util.find_spec("torchvision" if manifest.backend == "ssdlite320" else "transformers") is not None)
            if manifest.backend == "rtdetr-v2-r18":
                available = available and all((manifest_path.parent / name).is_file()
                    for name in ("config.json", "preprocessor_config.json"))
            records.append({"id": model_id, "name": model_id, "license": manifest.license,
                "weights_license": manifest.weights_license, "available": available, "synthetic": False,
                "backend": manifest.backend, "classes": list(manifest.classes), "path": str(manifest_path.parent),
                "description": "Locally trained detector; requires independent evaluation.", "estimated_fps": None})
        except (OSError, ValueError) as exc:
            records.append({"id": model_id, "name": model_id, "license": "unverified", "available": False,
                            "synthetic": False, "backend": "ssdlite320", "error": str(exc)})
    return records


def validate_model(model_id: str, *, allow_agpl: bool = False) -> None:
    record = next((item for item in list_models() if item["id"] == model_id), None)
    if record is None:
        raise ModelUnavailable(f"Unknown local model '{model_id}'. Register and review its license first.")
    license_name = str(record["license"])
    if "AGPL" in license_name:
        if not allow_agpl:
            raise ModelUnavailable(f"Model '{model_id}' requires explicit AGPL opt-in")
    elif license_name not in {"MIT", "Apache-2.0", "BSD-3-Clause architecture; project-trained weights", "macOS system framework"}:
        raise ModelUnavailable(f"Model '{model_id}' has an unapproved license: {license_name}")
    if not record["available"]:
        if model_id == "owlv2-base-patch16":
            raise ModelUnavailable(
                "OWLv2 is not installed. Install the vision extra and place the official "
                f"google/owlv2-base-patch16-ensemble snapshot in {owlv2_path()}. "
                "No model was downloaded or substituted.")
        raise ModelUnavailable(f"Model '{model_id}' is unavailable on this installation")
    if model_id == "apple-vision":
        raise ModelUnavailable("apple-vision is a reading backend; use the ocr or barcode block")


def trained_classes(model_id: str) -> list[str] | None:
    """None means an open-vocabulary adapter; closed checkpoints advertise classes."""
    if model_id == "rtdetr-v2-r18":
        path = rtdetr_path() / "config.json"
        if not path.is_file():
            return []
        config = json.loads(path.read_text())
        mapping = config.get("id2label") if isinstance(config, dict) else None
        if not isinstance(mapping, dict) or not mapping or not all(isinstance(value, str) for value in mapping.values()):
            raise ModelUnavailable("RT-DETRv2 checkpoint has no valid class mapping")
        return list(mapping.values())
    if model_id.startswith("local-"):
        from engine.models.local_manifest import read_manifest
        return read_manifest(model_id, model_directory()).classes
    return None
