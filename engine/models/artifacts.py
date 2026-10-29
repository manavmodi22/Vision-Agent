"""Content identities for local model artifacts and cached model instances."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from engine.models.manager import ModelUnavailable, model_directory, owlv2_path, rtdetr_path


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _change_token(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=512)
def _content_hash(path_string: str, token: tuple[int, int, int, int, int]) -> str:
    path = Path(path_string)
    content = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            content.update(chunk)
    if _change_token(path) != token:
        raise ModelUnavailable("Model artifact changed while hashing; retry after installation finishes")
    return content.hexdigest()


def content_hash(path: Path) -> str:
    # Metadata only invalidates the cache; identities always contain content SHA256.
    # ctime and inode catch in-place writes with restored mtime and atomic replacement.
    try:
        return _content_hash(str(path.resolve()), _change_token(path))
    except OSError as exc:
        raise ModelUnavailable(f"Cannot verify local artifact {path.name}: {exc}") from exc


def model_path(model_id: str) -> Path:
    if model_id == "owlv2-base-patch16":
        return owlv2_path()
    if model_id == "rtdetr-v2-r18":
        return rtdetr_path()
    if model_id.startswith("local-"):
        from engine.models.local_manifest import local_model_path
        return local_model_path(model_id, model_directory())
    raise ModelUnavailable(f"No learned-model artifact adapter for '{model_id}'")


def model_artifacts(model_id: str) -> tuple[dict[str, str], list[str]]:
    path = model_path(model_id)
    required = ["model.safetensors", "manifest.json"] if model_id.startswith("local-") else [
        "model.safetensors", "config.json", "preprocessor_config.json"]
    artifacts = {item.name: content_hash(item) for item in sorted(path.glob("*"))
                 if item.is_file() and item.suffix in {".json", ".txt", ".model", ".safetensors", ".vocab"}}
    return artifacts, [name for name in required if name not in artifacts]


def model_content_fingerprint(model_id: str) -> str:
    artifacts, missing = model_artifacts(model_id)
    if missing:
        raise ModelUnavailable(f"Local model '{model_id}' is missing: {', '.join(missing)}")
    return canonical_hash(artifacts)


def assert_model_fingerprint(model_id: str, expected: str) -> None:
    if model_content_fingerprint(model_id) != expected:
        raise ModelUnavailable("Model artifacts changed while loading or running; rebuild and evaluate")
