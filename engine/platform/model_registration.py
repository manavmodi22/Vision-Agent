"""Declare the purpose of a fresh, approved training output; never its quality."""
from pathlib import Path

from pydantic import JsonValue

from engine.eval.hashes import file_hash
from engine.models.local_manifest import read_manifest
from engine.store.repository import atomic_model
from engine.train.contracts import TrainingResult


def register_user_candidate(result: TrainingResult, expected_id: str, expected_path: Path,
                            training_hash: str, evaluation_hash: str, evidence_ref: str) -> dict[str, JsonValue]:
    if result.model_id != expected_id or Path(result.model_path).resolve() != expected_path.resolve():
        raise ValueError("Training returned a different model output; its registration was not changed")
    manifest_path, weights_path = expected_path / "manifest.json", expected_path / "model.safetensors"
    if any(path.is_symlink() for path in (expected_path, manifest_path, weights_path)):
        raise ValueError("A fresh training output must not refer to pre-existing files through links")
    record = read_manifest(expected_id, expected_path.parent)
    if (record.use_scope != "unknown" or record.use_scope_evidence_ref
            or record.training_hash != training_hash or result.training_hash != training_hash
            or record.evaluation_hash != evaluation_hash or result.evaluation_hash != evaluation_hash
            or record.backend != result.backend or record.base_model_id != result.base_model_id
            or record.classes != result.classes or record.steps != result.steps or record.steps < 1
            or record.training_samples != result.training_samples):
        raise ValueError("Fresh training output provenance does not match the approved job; registration unchanged")
    weights_hash = file_hash(weights_path)
    previous_manifest_hash = file_hash(manifest_path)
    record.use_scope, record.use_scope_evidence_ref = "user_candidate", evidence_ref
    record.training_state = "optimization_completed"
    atomic_model(manifest_path, record)
    return {"model_id":expected_id, "use_scope":"user_candidate", "evidence_ref":evidence_ref,
        "weights_sha256":weights_hash, "previous_manifest_sha256":previous_manifest_hash,
        "registered_manifest_sha256":file_hash(manifest_path), "training_hash":training_hash,
        "evaluation_hash":evaluation_hash, "quality_status":"unassessed"}
