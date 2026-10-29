"""Materialize a proposed edit without compiling, previewing or saving it."""
import json

from pydantic import JsonValue

from agent.contracts import PatternChoice
from agent.model_selection import selected_option
from engine.builds.refinement_edits import apply_edit, detector_classes
from engine.service import WorkspaceService
from spec.model_bindings import validate_block_bindings
from spec.models import PipelineSpec
from spec.planning import CandidateModelSelection, PlanningOptions
from spec.refinement import RefinementBatch, RefinementPatch


def validate_refinement_bindings(original: list[PipelineSpec], candidates: list[PipelineSpec],
                                 selections: list[CandidateModelSelection], options: PlanningOptions) -> None:
    """Carry model evidence only across edits that retain every inference identity."""
    kinds = {"detect", "detect_open_vocab", "ocr", "barcode"}

    def inference(spec: PipelineSpec) -> dict[str, tuple[str, JsonValue]]:
        if len({block.id for block in spec.blocks}) != len(spec.blocks):
            raise ValueError("Refinement cannot inherit bindings for duplicate block IDs")
        return {block.id: (block.type, block.params.get("model", "apple-vision"
                    if block.type in {"ocr", "barcode"} else None))
                for block in spec.blocks if block.type in kinds}

    if len(original) != len(candidates) or any(
        before.inputs != after.inputs or inference(before) != inference(after)
        for before, after in zip(original, candidates, strict=True)
    ):
        raise ValueError("Refinement changed an inference identity, model or source; capture a new model plan")
    if not selections or any(item.candidate_index >= len(candidates) for item in selections):
        raise ValueError("The originating plan has missing or extra model bindings")
    composed = any(item.block_id is not None for item in selections)
    if composed and any(item.block_id is None for item in selections):
        raise ValueError("The originating plan mixes composed and legacy model bindings")
    for index, candidate in enumerate(candidates):
        bindings = [item for item in selections if item.candidate_index == index]
        blocks = [block for block in candidate.blocks if block.type in kinds]
        if composed:
            validate_block_bindings(original[index], selections, index, options)
            validate_block_bindings(candidate, selections, index, options)
        elif len(bindings) != 1 or len(blocks) != 1:
            raise ValueError("Legacy model bindings must identify exactly one inference block per candidate")
        for block in blocks:
            binding = next((item for item in bindings if item.block_id == block.id), None) if composed else bindings[0]
            assert binding is not None
            reading = block.type in {"ocr", "barcode"}
            choice = PatternChoice.model_validate({"use_case": "custom",
                "pipeline_type": block.type if reading else "detection",
                "objects": [] if reading else block.params.get("classes", ["pallet"]),
                "model_capability_id": binding.capability_id, "model_reason": binding.proposed_reason,
                "metric": "text_accuracy" if reading else candidate.eval.metric,
                "target": .95 if reading else candidate.eval.target})
            option = selected_option(choice, options)
            if (binding.options_snapshot_id != options.snapshot_id or binding.model_id != option.model_id
                    or binding.adapter_id != option.adapter_id or inference(candidate)[block.id][1] != option.model_id):
                raise ValueError("The inherited model binding differs from the captured capability")


def refinement_candidates(service: WorkspaceService, project_id: str, request: dict[str, JsonValue]) -> list[PipelineSpec]:
    candidates = [spec.model_copy(deep=True) for spec in service.get_project(project_id).candidates]
    batch = RefinementBatch.model_validate(request["batch"]) if "batch" in request else RefinementBatch(
        patches=[RefinementPatch.model_validate(request.get("patch"))])
    selected = request.get("candidate_index", 0)
    if not isinstance(selected, int) or not 0 <= selected < len(candidates):
        raise ValueError("Choose an existing candidate")
    names = {name.casefold(): name for candidate in candidates for name in detector_classes(candidate)}
    path = service.root(project_id) / "dataset-metadata.json"
    if path.exists():
        names.update({item["name"].casefold(): item["name"] for item in json.loads(path.read_text()).get("classes", [])})
    for patch in batch.patches:
        for index in range(len(candidates)) if patch.target_scope() == "all" else [selected]:
            apply_edit(candidates[index], patch, names)
        names.update({name.casefold(): names.get(name.casefold(), name) for name in patch.classes})
    return [PipelineSpec.model_validate(spec.model_dump()) for spec in candidates]
