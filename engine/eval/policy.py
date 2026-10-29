"""Evidence adequacy follows an explicit scope declaration, never image counts."""
from __future__ import annotations

from pathlib import Path

from engine.eval.configuration import _read_configuration
from engine.eval.recipe import unscored_behaviors
from engine.eval.usage import ExposureSnapshot
from engine.evidence_metadata import unique_images
from spec.models import EvalDataset, PipelineSpec


def acceptance_blockers(root: Path, dataset: EvalDataset, candidates: list[PipelineSpec], candidate_index: int,
                        *, exclude_protocol: str | None = None) -> list[str]:
    if not 0 <= candidate_index < len(candidates):
        return ["Select one existing candidate before acceptance"]
    config = _read_configuration(root, dataset)
    policy = config.policy
    snapshot = ExposureSnapshot(root, config.images)
    reasons = unscored_behaviors(candidates[candidate_index])
    spec = candidates[candidate_index]
    kinds = {block.type for block in spec.blocks}
    detection = bool(kinds & {"detect", "detect_open_vocab"})
    reading = bool(kinds & {"ocr", "barcode"})
    judgement = "vlm_judge" in kinds
    if reading and spec.eval.metric != "text_accuracy":
        reasons.append("Reading acceptance requires the text_accuracy metric; detection/count metrics do not score text")
    if detection and spec.eval.metric == "text_accuracy":
        reasons.append("Detection acceptance requires precision, recall or count_mae; empty text cannot establish detection quality")
    if sum((detection, reading, judgement)) != 1 or {"ocr", "barcode"} <= kinds:
        reasons.append("This recipe qualifies one output task; mixed or missing inference outputs need separate acceptance protocols")
    if not all(value.strip() for value in (policy.intended_use, policy.independent_group_basis, policy.coverage_rationale)):
        reasons.append("Declare intended use, independent group basis and coverage rationale")
    if not policy.required_acceptance_groups:
        reasons.append("Explicitly name the scene groups required for acceptance")
    acceptance = [row for row in config.images if row.split == "acceptance"]
    source_scenes: dict[str, set[str]] = {}
    for row in acceptance:
        if row.source_sha256 and row.scene_group:
            source_scenes.setdefault(row.source_sha256, set()).add(row.scene_group)
    if any(len(groups) > 1 for groups in source_scenes.values()):
        reasons.append("One original source asset cannot satisfy multiple independent acceptance groups; assign it one scene group")
    if not acceptance:
        reasons.append("Reserve acceptance images before model preview, proposals, training or selection")
    represented = {row.scene_group for row in acceptance if row.scene_group}
    if set(policy.required_acceptance_groups) - represented:
        reasons.append("Not all required acceptance scene groups are represented")
    if represented - set(policy.required_acceptance_groups):
        reasons.append("Declare every reserved acceptance scene group in the required coverage policy")
    if any(row.scene_group is None or row.source_sha256 is None for row in acceptance):
        reasons.append("Acceptance needs declared scene groups and recorded original source identities; legacy unknown provenance is sample evidence")
    if any(row.data_origin != "real" for row in acceptance):
        reasons.append("Unknown or synthetic data cannot establish acceptance of real-world behavior")
    reviewed = {str((root / row.image_path).resolve()): row.reviewed for row in dataset.annotations}
    if any(not reviewed.get(str((root / row.image_path).resolve())) for row in acceptance):
        reasons.append("Every acceptance image must receive explicit human ground-truth review")
    development = [row for row in config.images if row.split in {"train", "validation"}
                   or (row.split != "acceptance" and snapshot.reasons(row.image_path))]
    if not any(row.scene_group and row.source_sha256 for row in development):
        reasons.append("Record at least one known development group to establish project-level separation")
    for row in acceptance:
        if any(other.image_path != row.image_path and other.split != "acceptance"
               for other in config.images if other.image_path in snapshot.paths[snapshot.find(row.image_path)]):
            reasons.append("Acceptance shares a declared scene or original source asset with development/unassigned images")
        if snapshot.reasons(row.image_path, exclude_protocol):
            reasons.append("Acceptance scene content has already been used by a model; reserve fresh groups")
    try:
        unique_images(root, [row.image_path for row in acceptance])
    except ValueError as exc:
        reasons.append(str(exc))
    dev_tokens = set().union(*(snapshot.tokens[row.image_path] for row in development)) if development else set()
    if any(snapshot.tokens[row.image_path] & dev_tokens for row in acceptance):
        reasons.append("Acceptance overlaps development pixels, bytes, scene or source identity")
    if any(block.params.get("model") == "fixture-color-v1" for block in candidates[candidate_index].blocks):
        reasons.append("The synthetic test detector cannot qualify for real-world promotion")
    return list(dict.fromkeys(reasons))
