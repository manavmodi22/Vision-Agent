"""Bind scoring semantics and distinguish output tasks before comparison."""
from __future__ import annotations

from pathlib import Path

from engine.blocks.params import DetectParams, ReadingParams
from engine.compiler import CompiledPipeline, compile_pipeline, parse_reference
from engine.eval.scope import detection_scope
from engine.models.artifacts import canonical_hash, content_hash
from spec.models import BlockSpec, PipelineSpec

RECIPE_VERSION = "reviewed-images-v3"
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


def _event_source(block: BlockSpec, compiled: CompiledPipeline, nodes: dict[str, BlockSpec]) -> str:
    """Canonical event ancestry without generated IDs or model experiment choices."""
    params = compiled.params[block.id]
    if block.type in {"detect", "detect_open_vocab"}:
        return canonical_hash({"task": "detection", "classes": sorted(DetectParams.model_validate(block.params).classes)})
    if block.type in {"ocr", "barcode"}:
        return canonical_hash({"task": block.type,
            "languages": ReadingParams.model_validate(block.params).languages if block.type == "ocr" else []})
    if block.type == "vlm_judge":
        return canonical_hash({"task": "vlm_judge", "question": block.params.get("question"),
                               "labels": block.params.get("labels")})
    upstream = {port: _event_source(nodes[owner], compiled, nodes)
                for port, reference in block.inputs.items()
                if (owner := parse_reference(reference)[0]) != "inputs"}
    if block.type == "zone_filter":
        return canonical_hash({"type": block.type, "zones": [zone.model_dump(mode="json")
                               for zone in compiled.zones[block.id]], "inputs": upstream})
    return canonical_hash({"type": block.type, "params": params.model_dump(mode="json"), "inputs": upstream})


def task_signature(spec: PipelineSpec, root: Path) -> str:
    compiled = compile_pipeline(spec, root)
    scope = detection_scope(compiled)
    nodes = {block.id: block for block in compiled.blocks}
    return canonical_hash({"classes": sorted(scope.classes),
        "zones": [[zone.model_dump(mode="json") for zone in stage] for stage in scope.zone_stages],
        "readers": sorted(canonical_hash({"task": block.type,
            "languages": ReadingParams.model_validate(block.params).languages if block.type == "ocr" else []})
            for block in spec.blocks if block.type in {"ocr", "barcode"}),
        "behaviors": sorted(_event_source(block, compiled, nodes)
                            for block in spec.blocks if block.type in {"rule", "match"}),
        "event_outputs": sorted(_event_source(block, compiled, nodes)
                                for block in spec.blocks if block.type == "sink_event"),
        "judgements": [{"question": block.params.get("question"), "labels": block.params.get("labels")}
                       for block in spec.blocks if block.type == "vlm_judge"]})


def unscored_behaviors(spec: PipelineSpec) -> list[str]:
    reasons = []
    if any(block.type in {"rule", "match", "sink_event"} for block in spec.blocks):
        reasons.append("This image recipe does not score event correctness, false alarms or temporal duration; numeric image scores are diagnostic only")
    kinds = {block.type for block in spec.blocks}
    detection = bool(kinds & {"detect", "detect_open_vocab"})
    reading = bool(kinds & {"ocr", "barcode"})
    judgement = "vlm_judge" in kinds
    if reading and spec.eval.metric != "text_accuracy":
        reasons.append("Reading acceptance requires the text_accuracy metric; detection/count metrics do not score text")
    if detection and spec.eval.metric == "text_accuracy":
        reasons.append("Detection acceptance requires precision, recall or count_mae; text accuracy cannot establish detection quality")
    if sum((detection, reading, judgement)) != 1 or {"ocr", "barcode"} <= kinds:
        reasons.append("This recipe qualifies one output task; mixed or missing inference outputs need separate acceptance protocols")
    if sum(block.type in {"ocr", "barcode", "vlm_judge"} for block in spec.blocks) > 1:
        reasons.append("Text accuracy scores the deduplicated union of text-producing branches, not each reader separately; per-branch quality gates are required for acceptance")
    return reasons
