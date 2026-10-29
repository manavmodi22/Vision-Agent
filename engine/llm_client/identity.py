"""Verify advertised vision support and bind evidence to a served model identity."""
from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

import httpx
from pydantic import JsonValue

from engine.llm_client.contracts import VLMConfig, VLMError, VLMPreflight
from engine.models.manager import model_directory


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=8)
def _artifact_hash(path: str, size: int, modified: int) -> str:
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _advertised_vision(record: dict[str, JsonValue], props: dict[str, JsonValue]) -> bool:
    architecture = _object(record.get("architecture"))
    modalities = architecture.get("input_modalities")
    if isinstance(modalities, list) and "image" in modalities:
        return True
    capabilities = record.get("capabilities")
    if isinstance(capabilities, list) and any(item in capabilities for item in ("vision", "multimodal", "image")):
        return True
    if isinstance(capabilities, dict) and capabilities.get("vision") is True:
        return True
    return _object(props.get("modalities")).get("vision") is True


def preflight(config: VLMConfig, *, client: httpx.Client | None = None, deadline: float | None = None) -> VLMPreflight:
    """Read-only preflight; actual image acceptance is verified by judge_image."""
    if client is None:
        with httpx.Client(timeout=min(config.timeout_s, 5), trust_env=False, follow_redirects=False) as owned:
            return preflight(config, client=owned, deadline=deadline)
    def request_timeout() -> float:
        remaining = min(config.timeout_s, 5) if deadline is None else min(config.timeout_s, 5, deadline - time.monotonic())
        if remaining <= 0:
            raise VLMError("VLM wall-clock budget expired during model preflight")
        return remaining

    try:
        response = client.get(config.base_url + "/models", timeout=request_timeout())
        response.raise_for_status()
        listing = cast("dict[str, JsonValue]", response.json())
        if not isinstance(listing, dict) or not isinstance(listing.get("data"), list):
            raise VLMError("VLM /models response has no typed model list")
        records = [_object(value) for value in cast("list[JsonValue]", listing["data"])]
        record = next((item for item in records if item.get("id") == config.model), None)
        if record is None:
            raise VLMError(f"VLM model '{config.model}' is not loaded at {config.base_url}")
        props_response = client.get(config.base_url.removesuffix("/v1") + "/props", timeout=request_timeout())
        props: dict[str, JsonValue] = {}
        if props_response.status_code == 200:
            props = _object(cast("JsonValue", props_response.json()))
        elif props_response.status_code not in {404, 405}:
            props_response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, VLMError):
            raise
        raise VLMError(f"Local VLM preflight failed: {exc}") from exc
    if not _advertised_vision(record, props):
        raise VLMError("Configured model does not explicitly advertise image input. Load a vision model and its projector.")
    prop_alias = props.get("model_alias")
    if isinstance(prop_alias, str) and prop_alias != config.model:
        raise VLMError("Model identity differs between /models and /props")
    # llama.cpp emits the current request time as `created`; it is not a load epoch.
    stable_record = {key: value for key, value in record.items() if key != "created"}
    identity: dict[str, JsonValue] = {"record": stable_record, "config": config.model_dump(mode="json")}
    stable_props: dict[str, JsonValue] = {key: props[key] for key in (
        "model_alias", "model_ftype", "model_path", "modalities", "build_info",
        "chat_template_caps", "default_generation_settings", "media_marker") if key in props}
    template = props.get("chat_template")
    if isinstance(template, str):
        stable_props["chat_template_sha256"] = hashlib.sha256(template.encode()).hexdigest()
    identity["server_properties"] = stable_props
    path_value = props.get("model_path")
    weights_hash = None
    scope: Literal["local_weights_verified", "server_metadata_only"] = "server_metadata_only"
    warnings = ["VLM labels and self-reported confidence are model hypotheses; confidence is not calibrated."]
    license_name = "Not verified; consult the model card"
    if isinstance(path_value, str):
        path = Path(path_value).expanduser().resolve()
        trusted_roots = [(Path.home() / ".lmstudio/models").resolve(), model_directory().resolve()]
        if path.suffix == ".gguf" and path.is_file() and any(path.is_relative_to(root) for root in trusted_roots):
            stat = path.stat()
            weights_hash = _artifact_hash(str(path), stat.st_size, stat.st_mtime_ns)
            identity["weights_sha256"] = weights_hash
            scope = "local_weights_verified"
            if "Cosmos-Reason2" in path.name:
                license_name = "NVIDIA Open Model License"
    if config.model_sha256 and weights_hash != config.model_sha256:
        raise VLMError("Pinned VLM weight digest cannot be verified against the currently served local model")
    if weights_hash is None:
        warnings.append("Server metadata identifies this model; its weight bytes cannot be verified through this endpoint.")
    warnings.append("Projector bytes are not exposed by the API; model-server identity changes invalidate evaluation.")
    return VLMPreflight(model=config.model, base_url=config.base_url, vision_supported=True,
        identity_hash=_canonical_hash(identity), identity_scope=scope,
        weights_sha256=weights_hash, model_license=license_name, warnings=warnings)
