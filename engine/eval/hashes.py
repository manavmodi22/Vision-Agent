"""Canonical fingerprints bind score evidence to labels, pixels and zone files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import JsonValue

from engine.adapters.identity import resolve_execution_identity
from engine.adapters.requests import request_for_block
from spec.models import EvalDataset, PipelineSpec


def digest(value: JsonValue) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Evaluation evidence file is missing: {path}")
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def spec_hash(spec: PipelineSpec, project_root: Path | None = None) -> str:
    payload = spec.model_dump(mode="json", by_alias=True)
    if project_root is not None:
        dependencies = {}
        for block in spec.blocks:
            zones = block.params.get("zones", "zones/lanes.json")
            if block.type == "zone_filter" and isinstance(zones, str):
                path = (project_root / zones).resolve()
                if not path.is_relative_to(project_root.resolve()):
                    raise ValueError("Zone file must be inside the project")
                dependencies[zones] = file_hash(path)
        payload["zone_file_hashes"] = dependencies
    payload["adapter_identities"] = {
        block.id: resolve_execution_identity(request).identity_hash
        for block in spec.blocks if (request := request_for_block(block)) is not None
    }
    vlm_identities = {}
    for block in spec.blocks:
        if block.type == "vlm_judge":
            from engine.blocks.params import VLMJudgeParams
            from engine.llm_client import preflight
            params = VLMJudgeParams.model_validate(block.params)
            vlm_identities[block.id] = preflight(params.client_config()).identity_hash
    if vlm_identities:
        payload["vlm_identities"] = vlm_identities
    return digest(payload)


def dataset_hash(dataset: EvalDataset, project_root: Path | None = None) -> str:
    payload = dataset.model_dump(mode="json")
    root = project_root or Path.cwd()
    payload["image_hashes"] = {annotation.image_path: file_hash(root / annotation.image_path)
                               for annotation in dataset.annotations}
    return digest(payload)
