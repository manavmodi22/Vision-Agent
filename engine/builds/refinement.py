"""Compile and preview a complete edit batch before its guarded atomic commit."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from engine.builds.refinement_commit import commit_refinement
from engine.builds.refinement_edits import apply_edit, detector_classes
from engine.compiler import compile_pipeline
from engine.datasets import PALETTE, DatasetClass, DatasetConflict, DatasetMetadata, DatasetService
from engine.eval import dataset_hash, spec_hash
from engine.media import media_fingerprint
from engine.runtime import run_pipeline
from engine.service import WorkspaceService
from spec.models import PipelineSpec
from spec.refinement import RefinementBatch, RefinementPatch, RefinementResult


def inputs_fingerprint(service: WorkspaceService, project_id: str) -> str:
    from engine.eval.protocol import stable_configuration_hash
    from engine.eval.recipe import recipe_hash
    root, project = service.root(project_id), service.get_project(project_id)
    documents = {name: (root / name).read_text() if (root / name).exists() else None
                 for name in ("project.json", "dataset-metadata.json", "active-holdout.json",
                              "deployment.json", "eval-media.json")}
    documents.update({str(path.relative_to(root)): path.read_text()
                      for path in sorted((root / "zones").glob("*.json"))})
    documents["evaluation_configuration"] = stable_configuration_hash(root, service.annotations(project_id))
    documents["evaluation_recipe"] = recipe_hash()
    value = {"documents": documents, "candidates": [spec_hash(spec, root) for spec in project.candidates],
             "annotations": dataset_hash(service.annotations(project_id), root),
             "media": media_fingerprint(project.media)}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_candidate(candidate: PipelineSpec, root: Path, fixture: bool) -> None:
    source = candidate.inputs["source"]
    if source.type != "image_folder" or (root / source.path).resolve() != (root / "media").resolve():
        raise ValueError("App pipelines must use the imported project media folder")
    if not fixture and any(block.params.get("model") == "fixture-color-v1" for block in candidate.blocks):
        raise ValueError("Fixture detector is only valid in the synthetic walkthrough")
    compile_pipeline(candidate, root)


def refine_app(service: WorkspaceService, project_id: str,
               patch: RefinementPatch | RefinementBatch, candidate_index: int = 0) -> RefinementResult:
    patches = patch.patches if isinstance(patch, RefinementBatch) else [patch]
    datasets = DatasetService(service)
    with service.repository.lock:
        project = service.get_project(project_id).model_copy(deep=True)
        if not 0 <= candidate_index < len(project.candidates):
            raise ValueError("Select an existing pipeline candidate")
        root = service.root(project_id)
        datasets.manifest(project_id)  # Synchronize legacy edits before taking our snapshot.
        metadata = DatasetMetadata.model_validate_json((root / "dataset-metadata.json").read_text())
        dataset = service.annotations(project_id).model_copy(deep=True)
        before = inputs_fingerprint(service, project_id)
        originals = [candidate.model_copy(deep=True) for candidate in project.candidates]
        before_hashes = {str(index): spec_hash(spec, root) for index, spec in enumerate(originals)}
        old_classes = list(metadata.classes)
        names = {item.name.casefold(): item.name for item in old_classes}
    affected: set[int] = set()
    for edit in patches:
        indices = list(range(len(project.candidates))) if edit.target_scope() == "all" else [candidate_index]
        if edit.kind == "remove_classes":
            available = {name.casefold() for index in indices for name in detector_classes(project.candidates[index])}
            missing = {name.casefold() for name in edit.classes} - available
            if missing:
                raise ValueError("These classes are not in the targeted detectors: " + ", ".join(sorted(missing)))
        for index in indices:
            apply_edit(project.candidates[index], edit, names)
            affected.add(index)
        for name in edit.classes:
            names.setdefault(name.casefold(), name)
    # Validate the final batch, allowing an intermediate remove-all then add.
    for index in affected:
        project.candidates[index] = PipelineSpec.model_validate(project.candidates[index].model_dump())
        validate_candidate(project.candidates[index], root, project.fixture)
    gained = {name for index in affected for name in detector_classes(project.candidates[index])
              if name.casefold() not in {old.casefold() for old in detector_classes(originals[index])}}
    for name in sorted(gained):
        if name.casefold() not in {item.name.casefold() for item in metadata.classes}:
            metadata.classes.append(DatasetClass(id="class-" + uuid.uuid4().hex[:12], name=name,
                color=PALETTE[len(metadata.classes) % len(PALETTE)]))
    if len(metadata.classes) > 200:
        raise ValueError("The dataset supports at most 200 object classes")
    if gained:
        for annotation in dataset.annotations:
            annotation.reviewed = False
    expected = {str(index): spec_hash(project.candidates[index], root) for index in affected}
    previews = {}
    for index in sorted(affected):
        previews[index] = run_pipeline(project.candidates[index], root, max_frames=5)
        if not previews[index].frames:
            raise ValueError(f"Refined candidate {index + 1} did not produce a real sample preview")
    with service.repository.lock:
        if (inputs_fingerprint(service, project_id) != before or
                any(spec_hash(project.candidates[index], root) != expected[str(index)] for index in affected)):
            raise DatasetConflict("App, model, examples, ontology or annotations changed during refinement; retry against the current app")
        changed = project.candidates != originals
        if changed:
            commit_refinement(root, project, dataset, metadata, labels_changed=bool(gained),
                              classes_changed=metadata.classes != old_classes)
    message = (f"Applied {len(patches)} requested changes to {len(affected)} candidate(s), "
               f"with an actual preview of every affected candidate. Preserved unrelated settings and human labels.")
    if not changed:
        message = "The requested settings were already present; previewed the existing candidates without changing them."
    if gained:
        message += " Reset image review flags for added classes: " + ", ".join(sorted(gained)) + ". Review these before evaluation."
    return RefinementResult(preview=previews[candidate_index], candidate_index=candidate_index,
        message=message, base_spec_hash=before_hashes[str(candidate_index)], spec_hash=expected[str(candidate_index)],
        requires_review=bool(gained), affected_candidate_indices=sorted(affected),
        previewed_candidate_indices=sorted(previews), base_spec_hashes={str(i): before_hashes[str(i)] for i in affected},
        spec_hashes=expected)
