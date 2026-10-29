"""Bind scoring semantics and distinguish output tasks before comparison."""
from __future__ import annotations

from pathlib import Path

from engine.compiler import compile_pipeline
from engine.eval.scope import detection_scope
from engine.models.artifacts import canonical_hash, content_hash
from spec.models import PipelineSpec

RECIPE_VERSION = "reviewed-images-v2"
_ROOT = Path(__file__).resolve().parents[2]
def _current_recipe() -> str:
    files = sorted(path for name in ("engine/eval", "engine/runtime", "engine/blocks", "engine/compiler", "spec")
                   for path in (_ROOT / name).rglob("*.py"))
    files.append(_ROOT / "engine/evidence_metadata.py")
    return canonical_hash({str(path.relative_to(_ROOT)): content_hash(path) for path in files})


_LOADED_RECIPE = _current_recipe()


def recipe_hash() -> str:
    if _current_recipe() != _LOADED_RECIPE:
        raise ValueError("Evaluation recipe source changed in this process; restart the engine")
    return _LOADED_RECIPE


def task_signature(spec: PipelineSpec, root: Path) -> str:
    compiled = compile_pipeline(spec, root)
    scope = detection_scope(compiled)
    return canonical_hash({"classes": sorted(scope.classes),
        "zones": [[zone.model_dump(mode="json") for zone in stage] for stage in scope.zone_stages],
        "readers": sorted(block.type for block in spec.blocks if block.type in {"ocr", "barcode"}),
        "behaviors": sorted(canonical_hash({"type": block.type,
            "params": compiled.params[block.id].model_dump(mode="json")})
            for block in spec.blocks if block.type in {"rule", "match"}),
        "judgements": [{"question": block.params.get("question"), "labels": block.params.get("labels")}
                       for block in spec.blocks if block.type == "vlm_judge"]})


def unscored_behaviors(spec: PipelineSpec) -> list[str]:
    if any(block.type in {"rule", "match", "sink_event"} for block in spec.blocks):
        return ["This image recipe does not score event correctness, false alarms or temporal duration; numeric image scores are diagnostic only"]
    return []
