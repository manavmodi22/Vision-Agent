"""Bounded recorded training facts; no quality inference or artifact mutation."""
from typing import Literal

from engine.models.local_manifest import read_manifest
from engine.models.manager import model_directory
from spec.planning import ModelTrainingProvenance


def provenance(model_id: str) -> ModelTrainingProvenance:
    if model_id.startswith("local-"):
        record = read_manifest(model_id, model_directory())
        return ModelTrainingProvenance(origin="locally_trained", initialization=record.initialization,
            training_state=record.training_state, use_scope=record.use_scope,
            use_scope_evidence_ref=record.use_scope_evidence_ref, base_model_id=record.base_model_id,
            training_samples=record.training_samples, epochs_completed=record.epochs_completed,
            optimizer_steps=record.steps, preserved_classes=record.preserved_classes,
            evaluation_dataset_recorded=bool(record.evaluation_hash), provenance_scope="manifest_recorded")
    origin: Literal["system_framework", "synthetic", "upstream_pretrained"] = "system_framework" if model_id == "apple-vision" else "synthetic" if model_id == "fixture-color-v1" else "upstream_pretrained"
    return ModelTrainingProvenance(origin=origin, initialization="not_applicable",
        use_scope="engineering_smoke" if origin == "synthetic" else "upstream_baseline",
        provenance_scope="registry_recorded")


def default_exclusion(facts: ModelTrainingProvenance) -> str | None:
    if facts.origin != "locally_trained":
        return None
    if facts.use_scope == "engineering_smoke":
        return "Registered for engineering smoke checks; excluded from generic goals. An exact explicit model experiment is available."
    if facts.training_state == "untrained":
        return "Registered as untrained; excluded from generic goals. An exact explicit model experiment is available."
    if facts.use_scope != "user_candidate" or not (facts.use_scope_evidence_ref or "").strip():
        return "Local model suitability is unknown: no evidenced user-candidate registration. An exact explicit model experiment is available."
    return None
