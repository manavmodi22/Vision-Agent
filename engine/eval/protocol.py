"""Immutable protocols for validation comparisons or selected-candidate acceptance."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from engine.eval.configuration import (
    _read_configuration,
    evidence_lock,
    group_keys,
    read_configuration,
    reserved_acceptance_paths,
    save_configuration,
    selected_paths,
    stable_configuration_hash,
)
from engine.eval.hashes import dataset_hash, spec_hash
from engine.eval.policy import acceptance_blockers
from engine.eval.recipe import RECIPE_VERSION, recipe_hash, task_signature, unscored_behaviors
from engine.eval.usage import consume_acceptance, mark_pixel_usage, mark_usage
from engine.evidence_metadata import image_identity, relative_image, unique_images
from engine.models.artifacts import canonical_hash
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.evaluation import EvaluationProtocol, ProtocolCandidate, Purpose
from spec.models import EvalDataset, EvaluationResult, PipelineSpec

__all__ = ["read_configuration", "save_configuration", "stable_configuration_hash",
           "reserved_acceptance_paths", "mark_usage", "mark_pixel_usage", "acceptance_blockers", "freeze_protocol",
           "read_protocol", "protocol_dataset", "validate_evidence", "begin_evaluation", "task_signature"]


def read_protocol(root: Path, protocol_id: str) -> EvaluationProtocol:
    if not re.fullmatch(r"[a-f0-9]{32}", protocol_id):
        raise ValueError("Invalid evaluation protocol ID")
    path = root / "evaluation/protocols" / (protocol_id + ".json")
    if not path.is_file():
        raise ValueError("Evaluation protocol is missing; freeze a new comparison")
    protocol = EvaluationProtocol.model_validate_json(path.read_text())
    if protocol.protocol_hash != canonical_hash(protocol.model_dump(mode="json", exclude={"protocol_hash"})):
        raise ValueError("Stored evaluation protocol content does not match its immutable hash")
    return protocol


def membership_hash(root: Path, dataset: EvalDataset, paths: list[str]) -> str:
    rows = {row.image_path: row for row in _read_configuration(root, dataset).images}
    if any(path not in rows for path in paths):
        raise ValueError("Protocol membership refers to missing dataset images")
    return canonical_hash([{**rows[path].model_dump(mode="json", exclude={"exposure_reasons"}),
                             "content": image_identity(root, path)} for path in paths])


def freeze_protocol(root: Path, dataset: EvalDataset, candidates: list[PipelineSpec],
                    candidate_indices: list[int], purpose: Purpose = "validation") -> EvaluationProtocol:
    if (not candidate_indices or len(candidate_indices) != len(set(candidate_indices))
            or any(index < 0 or index >= len(candidates) for index in candidate_indices)):
        raise ValueError("Select unique existing candidates for evaluation")
    if purpose == "acceptance" and len(candidate_indices) != 1:
        raise ValueError("Acceptance tests one already-selected candidate, never ranks alternatives")
    with evidence_lock(root):
        selected = [candidates[index] for index in candidate_indices]
        signatures = {task_signature(candidate, root) for candidate in selected}
        if len(signatures) != 1 or len({(candidate.eval.metric, candidate.eval.target) for candidate in selected}) != 1:
            raise ValueError("Compared candidates must share output task, classes/zones/behavior, metric and target")
        paths = selected_paths(root, dataset, purpose)
        if not paths:
            raise ValueError("Assign a nonempty reviewed evaluation split first")
        unique_images(root, paths)
        config = _read_configuration(root, dataset)
        rows = [row for row in config.images if row.image_path in paths]
        values = {"purpose": purpose, "config_revision": config.revision,
            "dataset_hash": dataset_hash(dataset, root), "membership_hash": membership_hash(root, dataset, paths),
            "task_signature": next(iter(signatures)), "metric": selected[0].eval.metric, "target": selected[0].eval.target,
            "recipe_version": RECIPE_VERSION, "recipe_hash": recipe_hash(),
            "candidates": [ProtocolCandidate(candidate_index=index, spec_hash=spec_hash(candidates[index], root)).model_dump()
                           for index in candidate_indices], "image_paths": paths,
            "group_ids": sorted(set().union(*(group_keys(row) for row in rows))), "policy": config.policy.model_dump()}
        if purpose == "acceptance":
            for path in sorted((root / "evaluation/protocols").glob("*.json")):
                old = read_protocol(root, path.stem)
                if old.model_dump(mode="json", exclude={"id", "created_at", "protocol_hash"}) == values:
                    return old
            blockers = acceptance_blockers(root, dataset, candidates, candidate_indices[0])
            if blockers:
                raise ValueError("Acceptance is not ready: " + "; ".join(blockers))
        payload = {**values, "id": uuid.uuid4().hex, "created_at": now()}
        protocol = EvaluationProtocol.model_validate({**payload, "protocol_hash": canonical_hash(payload)})
        atomic_model(root / "evaluation/protocols" / (protocol.id + ".json"), protocol)
        return protocol


def protocol_dataset(root: Path, dataset: EvalDataset, protocol: EvaluationProtocol) -> EvalDataset:
    if read_protocol(root, protocol.id) != protocol:
        raise ValueError("Evaluation protocol was changed after freezing")
    if protocol.recipe_version != RECIPE_VERSION or protocol.recipe_hash != recipe_hash():
        raise ValueError("Evaluation recipe changed; re-evaluate")
    if protocol.config_revision != stable_configuration_hash(root, dataset):
        raise ValueError("Evaluation group assignments or policy changed; re-evaluate")
    if protocol.dataset_hash != dataset_hash(dataset, root):
        raise ValueError("Evaluation dataset or labels changed; re-evaluate")
    if protocol.membership_hash != membership_hash(root, dataset, protocol.image_paths):
        raise ValueError("Evaluation group membership/content changed; re-evaluate")
    annotations = {relative_image(root, row.image_path): row for row in dataset.annotations}
    unique_images(root, protocol.image_paths)
    return EvalDataset(id=dataset.id, annotations=[annotations[path].model_copy(deep=True) for path in protocol.image_paths])


def begin_evaluation(root: Path, dataset: EvalDataset, spec: PipelineSpec, protocol: EvaluationProtocol) -> EvalDataset:
    subset = protocol_dataset(root, dataset, protocol)
    if spec_hash(spec, root) not in {candidate.spec_hash for candidate in protocol.candidates}:
        raise ValueError("Candidate model or workflow changed after the protocol was frozen")
    if task_signature(spec, root) != protocol.task_signature:
        raise ValueError("Candidate output task differs from the evaluation protocol")
    if protocol.purpose == "acceptance":
        config = _read_configuration(root, dataset)
        rows = [row for row in config.images if row.image_path in protocol.image_paths]
        blockers = acceptance_blockers(root, dataset, [spec], 0, exclude_protocol=protocol.id)
        if blockers:
            raise ValueError("Acceptance evidence is no longer fresh: " + "; ".join(blockers))
        consume_acceptance(root, protocol.id, rows, config.images)
    else:
        mark_usage(root, protocol.image_paths, "validation evaluation")
    return subset


def attach_evidence(root: Path, dataset: EvalDataset, spec: PipelineSpec,
                    protocol: EvaluationProtocol, result: EvaluationResult) -> EvaluationResult:
    protocol_dataset(root, dataset, protocol)
    result.protocol_id, result.protocol_hash = protocol.id, protocol.protocol_hash
    result.evidence_scope = protocol.purpose
    if protocol.purpose == "acceptance":
        reasons = acceptance_blockers(root, dataset, [spec], 0, exclude_protocol=protocol.id)
        if not result.passed:
            reasons.append("The selected candidate did not meet the declared numeric target")
        result.promotion_eligible = not reasons and result.passed
        result.evidence_reasons = reasons or ["Acceptance is limited to the explicitly declared scene coverage; upstream pretraining overlap is unknown"]
    else:
        config = _read_configuration(root, dataset)
        selected = [row for row in config.images if row.image_path in protocol.image_paths]
        result.evidence_reasons = ["Validation informs model/threshold selection; it is not untouched acceptance"] + unscored_behaviors(spec)
        if any(not row.scene_group or not row.source_sha256 or row.data_origin != "real" for row in selected):
            result.evidence_scope = "sample"
            result.evidence_reasons.append("Unknown, synthetic or undeclared source grouping supports sample evidence only")
    return result


def validate_evidence(root: Path, dataset: EvalDataset, candidates: list[PipelineSpec], result: EvaluationResult) -> None:
    if not result.protocol_id or not result.protocol_hash:
        raise ValueError("Legacy result has no frozen evidence protocol; re-evaluate")
    protocol = read_protocol(root, result.protocol_id)
    subset = protocol_dataset(root, dataset, protocol)
    if result.protocol_hash != protocol.protocol_hash or result.dataset_hash != dataset_hash(subset, root):
        raise ValueError("Evaluation result does not match its frozen protocol/data")
    if result.metric != protocol.metric or result.target != protocol.target:
        raise ValueError("Evaluation metric/target changed")
    for candidate in protocol.candidates:
        if candidate.candidate_index >= len(candidates) or spec_hash(candidates[candidate.candidate_index], root) != candidate.spec_hash:
            raise ValueError("A compared candidate changed after evaluation")
    if result.spec_hash not in {candidate.spec_hash for candidate in protocol.candidates}:
        raise ValueError("Evaluation result refers to another candidate")
    if protocol.purpose == "acceptance":
        reasons = acceptance_blockers(root, dataset, candidates, protocol.candidates[0].candidate_index, exclude_protocol=protocol.id)
        if reasons:
            raise ValueError("Acceptance evidence is stale: " + "; ".join(reasons))
    if result.promotion_eligible and (protocol.purpose != "acceptance" or not result.passed):
        raise ValueError("Only a passing selected-candidate acceptance result can qualify for promotion")
