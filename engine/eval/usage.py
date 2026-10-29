"""Append-only model exposure, separate from human viewing and GT review."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from pydantic import Field

from engine.eval.configuration import (
    _read_configuration,
    evidence_lock,
    group_keys,
    project_dataset,
)
from engine.eval.history import annotation_model_reasons, legacy_exposures
from engine.evidence_metadata import image_identity, pixel_hash_image, relative_image, source_record
from engine.store.repository import atomic_model
from spec.evaluation import EvidenceImage
from spec.models import Contract, EvalDataset


class UsageLedger(Contract):
    uses: dict[str, list[str]] = Field(default_factory=dict)
    acceptance: dict[str, list[str]] = Field(default_factory=dict)


def read_usage(root: Path) -> UsageLedger:
    path = root / "evaluation/usage.json"
    return UsageLedger.model_validate_json(path.read_text()) if path.exists() else UsageLedger()


def image_tokens(root: Path, image: EvidenceImage) -> set[str]:
    identity = image_identity(root, image.image_path)
    source_hash = source_record(root, image.image_path).get("source_sha256")
    return ({"bytes:" + identity["bytes"], "pixels:" + identity["pixels"]} | group_keys(image)
            | ({"source:" + source_hash} if source_hash else set()))


class ExposureSnapshot:
    """One ledger read and one image hash/decode per image for this operation."""
    def __init__(self, root: Path, images: list[EvidenceImage], ledger: UsageLedger | None = None) -> None:
        self.ledger = ledger or read_usage(root)
        self.tokens = {row.image_path: image_tokens(root, row) for row in images}
        self.legacy = legacy_exposures(root, images)
        for path, reasons in self.legacy.items():
            for token in self.tokens.get(path, set()):
                self.ledger.uses[token] = sorted(set(self.ledger.uses.get(token, [])) | set(reasons))
        self.parents = {row.image_path: row.image_path for row in images}
        seen: dict[str, str] = {}
        for row in images:
            for key in self.tokens[row.image_path]:
                if key in seen:
                    self.parents[self.find(row.image_path)] = self.find(seen[key])
                else:
                    seen[key] = row.image_path
        self.groups: dict[str, set[str]] = {}
        self.paths: dict[str, set[str]] = {}
        for row in images:
            parent = self.find(row.image_path)
            self.groups.setdefault(parent, set()).update(self.tokens[row.image_path])
            self.paths.setdefault(parent, set()).add(row.image_path)

    def find(self, path: str) -> str:
        while self.parents[path] != path:
            self.parents[path] = self.parents[self.parents[path]]
            path = self.parents[path]
        return path

    def reasons(self, image_path: str, exclude_protocol: str | None = None) -> list[str]:
        tokens = self.groups[self.find(image_path)]
        reasons = {reason for token in tokens for reason in self.ledger.uses.get(token, [])}
        for protocol_id, consumed in self.ledger.acceptance.items():
            if protocol_id != exclude_protocol and tokens & set(consumed):
                reasons.add("Previously used for acceptance; use fresh scene groups after tuning")
        return sorted(reasons)


def exposure_map(root: Path, images: list[EvidenceImage]) -> dict[str, list[str]]:
    ledger = read_usage(root)
    snapshot = ExposureSnapshot(root, images, ledger)
    return {row.image_path: snapshot.reasons(row.image_path) for row in images}


def preserve_legacy_usage(root: Path, images: list[EvidenceImage]) -> None:
    """Caller holds evidence_lock; retain unknown legacy identity across reimports."""
    atomic_model(root / "evaluation/usage.json", ExposureSnapshot(root, images).ledger)


def preserve_annotation_usage(root: Path, previous: EvalDataset, incoming: EvalDataset, *,
                              imported_exposures: dict[str, list[str]] | None = None) -> None:
    """After caller validation, append old/new seed history before replacing labels.

    Caller holds the project write lock and has checked image membership, edit CAS,
    classes and the complete incoming payload. This function finishes all parsing
    and content reads before its single ledger write. A later filesystem failure
    may conservatively retain exposure, but must never lose known model use.
    """
    previous = EvalDataset.model_validate(previous.model_dump(mode="json"))
    incoming = EvalDataset.model_validate(incoming.model_dump(mode="json"))
    reasons: dict[str, set[str]] = {}
    allowed = {relative_image(root, row.image_path) for row in incoming.annotations}
    if len(allowed) != len(incoming.annotations):
        raise ValueError("Incoming annotations must refer to unique images")
    for dataset in (previous, incoming):
        for annotation in dataset.annotations:
            path = relative_image(root, annotation.image_path)
            reasons.setdefault(path, set()).update(annotation_model_reasons(annotation))
    imported = imported_exposures or {}
    if len(imported) > 5000:
        raise ValueError("Imported model history exceeds the image bound")
    seen: set[str] = set()
    for raw, values in imported.items():
        path = relative_image(root, raw)
        if path not in allowed or path in seen:
            raise ValueError("Imported model history must refer to unique incoming images")
        seen.add(path)
        if (not isinstance(values, list) or len(values) > 1000
                or any(not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in values)):
            raise ValueError("Imported model history requires at most 1000 nonempty bounded reasons per image")
        reasons.setdefault(path, set()).update(values)
    # A manual label edit removes no source/build history. With no seed or
    # imported model use to preserve, do not decode the dataset on each autosave.
    if not any(reasons.values()):
        return
    with evidence_lock(root):
        ledger = read_usage(root)
        before = ledger.model_dump_json()
        images = {row.image_path: row for dataset in (previous, incoming)
                  for row in _read_configuration(root, dataset).images}
        snapshot = ExposureSnapshot(root, list(images.values()), ledger)
        for path, reason_set in reasons.items():
            if reason_set:
                for token in snapshot.tokens[path]:
                    ledger.uses[token] = sorted(set(ledger.uses.get(token, [])) | reason_set)
        if ledger.model_dump_json() != before:
            atomic_model(root / "evaluation/usage.json", ledger)


def image_exposures(root: Path, image: EvidenceImage, images: list[EvidenceImage],
                    *, exclude_protocol: str | None = None) -> list[str]:
    return ExposureSnapshot(root, images).reasons(image.image_path, exclude_protocol)


def mark_usage(root: Path, image_paths: list[str], purpose: str) -> None:
    if purpose in {"human_review", "raw_view"}:
        return
    with evidence_lock(root):
        rows = {row.image_path: row for row in _read_configuration(root, project_dataset(root)).images}
        ledger = ExposureSnapshot(root, list(rows.values())).ledger
        for raw in image_paths:
            path = relative_image(root, raw)
            row = rows.get(path, EvidenceImage(image_path=path))
            for token in image_tokens(root, row):
                ledger.uses[token] = sorted(set(ledger.uses.get(token, [])) | {"Model use: " + purpose[:120]})
        atomic_model(root / "evaluation/usage.json", ledger)


def mark_pixel_usage(root: Path, image: Image.Image, purpose: str) -> None:
    """Record live model exposure without saving a frame or inventing its source."""
    if image.width * image.height > 40_000_000:
        raise ValueError("Live exposure images are limited to 40 megapixels")
    token = "pixels:" + pixel_hash_image(image)
    with evidence_lock(root):
        ledger = read_usage(root)
        if token not in ledger.uses and len(ledger.uses) >= 200000:
            raise ValueError("Project exposure ledger is full; archive the project before further model use")
        ledger.uses[token] = sorted(set(ledger.uses.get(token, [])) | {"Model use: " + purpose[:120]})
        atomic_model(root / "evaluation/usage.json", ledger)


def consume_acceptance(root: Path, protocol_id: str, rows: list[EvidenceImage],
                       all_rows: list[EvidenceImage]) -> None:
    with evidence_lock(root):
        snapshot = ExposureSnapshot(root, all_rows)
        if protocol_id in snapshot.ledger.acceptance:
            raise ValueError("Acceptance was already consumed; only replay an existing captured result, never rerun failed/interrupted attempts")
        for row in rows:
            if snapshot.reasons(row.image_path, protocol_id):
                raise ValueError("Acceptance groups have already been exposed to model development or another acceptance run")
        ledger = snapshot.ledger
        tokens = set().union(*(snapshot.groups[snapshot.find(row.image_path)] for row in rows))
        ledger.acceptance[protocol_id] = sorted(tokens)
        atomic_model(root / "evaluation/usage.json", ledger)
