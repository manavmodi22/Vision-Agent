"""Generate unverified annotations without changing human labels or saving files."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from engine.compiler import compile_pipeline, parse_reference
from engine.eval.hashes import file_hash, spec_hash
from engine.runtime.executor import execute_frame
from engine.runtime.values import ExecutionState
from spec.models import EvalDataset, PipelineSpec, ProposalEvidence


def _detection_chain(spec: PipelineSpec) -> tuple[PipelineSpec, str]:
    detectors = [block for block in spec.blocks if block.type in {"detect", "detect_open_vocab"}]
    if len(detectors) != 1:
        raise ValueError("Label proposals require exactly one detector in the selected candidate")
    model_id = str(detectors[0].params.get("model", "owlv2-base-patch16"))
    if model_id == "fixture-color-v1":
        raise ValueError("Rectangle fixture detections cannot become warehouse label proposals")
    blocks = {block.id: block for block in spec.blocks}
    selected = next((block.id for block in spec.blocks if block.type == "zone_filter"), detectors[0].id)
    needed: set[str] = set()

    def include(identifier: str) -> None:
        if identifier in needed:
            return
        if identifier not in blocks:
            raise ValueError("Detector chain has an unresolved block reference")
        needed.add(identifier)
        for reference in blocks[identifier].inputs.values():
            owner, _ = parse_reference(reference)
            if owner != "inputs":
                include(owner)

    include(selected)
    allowed = {"frame_sample", "crop", "resize", "detect", "detect_open_vocab", "zone_filter"}
    if any(blocks[name].type not in allowed for name in needed):
        raise ValueError("Label proposals support only image transforms, detection and zone filtering")
    return spec.model_copy(update={"blocks": [block for block in spec.blocks if block.id in needed]}, deep=True), model_id


def propose_labels(spec: PipelineSpec, dataset: EvalDataset, project_root: Path,
                   max_frames: int = 50) -> EvalDataset:
    """Fill empty unreviewed frames with detector hypotheses; never mark reviewed."""
    if not 1 <= max_frames <= 50:
        raise ValueError("Label proposals are limited to 1–50 images per request")
    if not dataset.annotations:
        raise ValueError("Import images before proposing labels")
    chain, model_id = _detection_chain(spec)
    compiled = compile_pipeline(chain, project_root)
    fingerprint = spec_hash(chain, project_root)
    proposed = dataset.model_copy(deep=True)
    used = 0
    for annotation in proposed.annotations:
        # Preserve reviewed frames, existing manual boxes, and prior proposals.
        if annotation.reviewed or annotation.detections or annotation.proposal is not None:
            continue
        if used >= max_frames:
            break
        path = (project_root / annotation.image_path).resolve()
        if not path.is_relative_to(project_root.resolve()):
            raise ValueError("Label proposal images must be imported inside the project")
        before = file_hash(path)
        frame = execute_frame(compiled, path, 0, ExecutionState())
        if file_hash(path) != before:
            raise ValueError("Image changed during label proposal; suggestions discarded")
        annotation.detections = frame.detections
        annotation.reviewed = False
        annotation.proposal = ProposalEvidence(model_id=model_id, spec_hash=fingerprint,
            image_sha256=before, created_at=datetime.now(UTC).isoformat())
        used += 1
    if spec_hash(chain, project_root) != fingerprint:
        raise ValueError("Detector or zone configuration changed during label proposals")
    return proposed


__all__ = ["propose_labels"]
