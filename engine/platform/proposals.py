"""Materialize a proposed edit without compiling, previewing or saving it."""
import json

from pydantic import JsonValue

from engine.builds.refinement_edits import apply_edit, detector_classes
from engine.service import WorkspaceService
from spec.models import PipelineSpec
from spec.refinement import RefinementBatch, RefinementPatch


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
