"""Compile a versioned graph into an ordered, fully type-checked execution plan."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from engine.adapters.identity import resolve_execution_identity
from engine.adapters.requests import request_for_block
from engine.blocks.logic import parse_rule
from engine.blocks.params import (
    CropParams,
    DetectParams,
    FrameSampleParams,
    ReadingParams,
    RuleParams,
    VLMJudgeParams,
    ZoneFilterParams,
)
from engine.blocks.registry import REGISTRY, PortType
from engine.blocks.spatial import load_zones
from engine.llm_client import VLMPreflight, preflight
from engine.models import validate_model
from engine.models.manager import trained_classes
from spec.inference import ExecutionIdentity
from spec.models import BlockSpec, Contract, PipelineSpec, Zone


class CompileError(ValueError):
    """The graph cannot safely or correctly execute."""


@dataclass(frozen=True)
class CompiledPipeline:
    spec: PipelineSpec
    blocks: tuple[BlockSpec, ...]
    params: dict[str, Contract]
    zones: dict[str, list[Zone]]
    warnings: tuple[str, ...]
    estimated_fps: float | None = None
    vlm_identities: dict[str, VLMPreflight] = field(default_factory=dict)
    inference_identities: dict[str, ExecutionIdentity] = field(default_factory=dict)


def parse_reference(reference: str) -> tuple[str, str]:
    if not reference.startswith("$") or reference.count(".") != 1:
        raise CompileError(f"Invalid input reference: {reference}")
    owner, port = reference[1:].split(".")
    if not owner or not port:
        raise CompileError(f"Invalid input reference: {reference}")
    return owner, port


def compile_pipeline(spec: PipelineSpec, project_root: Path, *, allow_agpl: bool = False) -> CompiledPipeline:
    nodes = {block.id: block for block in spec.blocks}
    if len(nodes) != len(spec.blocks) or "inputs" in nodes:
        raise CompileError("Block IDs must be unique; 'inputs' is reserved")
    if spec.inputs["source"].type in {"camera", "screen_capture"}:
        raise CompileError("Live camera/screen capture is not implemented; import a recording or image folder")
    if sum(block.type in {"detect", "detect_open_vocab"} for block in spec.blocks) > 1:
        raise CompileError("Version 0.1 evaluates one detector per candidate; split alternatives into separate candidates")
    if sum(block.type == "zone_filter" for block in spec.blocks) > 1:
        raise CompileError("Version 0.1 supports one zone filter per candidate")
    judges = [block for block in spec.blocks if block.type == "vlm_judge"]
    if len(judges) > 1:
        raise CompileError("Version 0.1 supports one visual judgement per candidate")
    if judges and spec.eval.metric != "text_accuracy":
        raise CompileError("VLM candidates must use text_accuracy against reviewed expected labels")
    definitions = {}
    params: dict[str, Contract] = {}
    zones: dict[str, list[Zone]] = {}
    warnings: list[str] = []
    vlm_identities: dict[str, VLMPreflight] = {}
    for block in spec.blocks:
        definition = REGISTRY.get(block.type)
        if definition is None:
            raise CompileError(f"Unsupported block '{block.type}'; no silent no-op is permitted")
        definitions[block.id] = definition
        try:
            value = definition.params.model_validate(block.params)
        except ValidationError as exc:
            raise CompileError(f"Invalid parameters for {block.id}: {exc}") from exc
        params[block.id] = value
        if isinstance(value, DetectParams):
            validate_model(value.model, allow_agpl=allow_agpl)
            classes = trained_classes(value.model)
            if classes is not None and set(value.classes) - set(classes):
                raise CompileError("Selected closed-vocabulary detector has not been trained for the requested classes; choose open-vocabulary proposals or a matching fine-tuned model")
            if value.model == "fixture-color-v1":
                warnings.append("SYNTHETIC FIXTURE: colored rectangles only. This does not validate warehouse detection.")
        if isinstance(value, VLMJudgeParams):
            identity = preflight(value.client_config())
            vlm_identities[block.id] = identity
            warnings.extend(identity.warnings)
        if isinstance(value, ZoneFilterParams):
            selected_zones = load_zones(value.zones, project_root)
            missing = set(value.include_ids) - {zone.id for zone in selected_zones}
            if missing:
                raise CompileError("Draw and save the requested regions first: " + ", ".join(sorted(missing)))
            zones[block.id] = [zone for zone in selected_zones if not value.include_ids or zone.id in value.include_ids]
        if isinstance(value, RuleParams):
            parse_rule(value.when)
            if value.hold_s > 0 and spec.inputs["source"].type != "video_file":
                warnings.append("Rule duration is not evaluated on independent images; verify elapsed-time behavior with timestamped video or live capture.")
        if isinstance(value, CropParams):
            x0, y0, x1, y1 = value.box
            if not 0 <= x0 < x1 <= 1 or not 0 <= y0 < y1 <= 1:
                raise CompileError("Crop box must be a normalized rectangle with positive area")
        if isinstance(value, ReadingParams) and value.languages != ["en-US"]:
            raise CompileError("This native bridge currently supports only en-US text recognition")
        if set(block.inputs) != set(definition.inputs):
            raise CompileError(f"{block.id} requires inputs {sorted(definition.inputs)}, got {sorted(block.inputs)}")
    sampling_rates = {value.fps for value in params.values() if isinstance(value, FrameSampleParams)}
    if len(sampling_rates) > 1:
        raise CompileError("Version 0.1 requires the same sampling rate across branches")
    dependencies: dict[str, set[str]] = {name: set() for name in nodes}
    for block in spec.blocks:
        for input_name, reference in block.inputs.items():
            owner, port = parse_reference(reference)
            actual: PortType
            if owner == "inputs":
                if port != "source":
                    raise CompileError(f"Unresolved source: {reference}")
                actual = "frames"
            else:
                if owner not in definitions or port not in definitions[owner].outputs:
                    raise CompileError(f"Unresolved output: {reference}")
                actual = definitions[owner].outputs[port]
                dependencies[block.id].add(owner)
            expected = definitions[block.id].inputs[input_name]
            if actual != expected:
                raise CompileError(f"Port mismatch at {block.id}.{input_name}: expected {expected}, got {actual}")
    ordered: list[BlockSpec] = []
    remaining = dict(dependencies)
    while remaining:
        ready = [name for name, deps in remaining.items() if not deps]
        if not ready:
            raise CompileError(f"Cycle detected among blocks: {', '.join(remaining)}")
        for name in ready:
            ordered.append(nodes[name])
            del remaining[name]
        for deps in remaining.values():
            deps.difference_update(ready)
    warnings.append("FPS is unbenchmarked on this Mac; runtime timings are measured, not predicted.")
    inference_identities = {block.id: resolve_execution_identity(request)
                            for block in ordered if (request := request_for_block(block)) is not None}
    return CompiledPipeline(spec, tuple(ordered), params, zones, tuple(dict.fromkeys(warnings)),
                            vlm_identities=vlm_identities, inference_identities=inference_identities)


__all__ = ["compile_pipeline", "CompiledPipeline", "CompileError", "parse_reference"]
