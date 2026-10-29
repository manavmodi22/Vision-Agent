"""Region geometry with explicit provenance bound to the saved coordinates."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from engine.store.repository import atomic_model
from spec.models import Contract, Zone


class ZoneDocument(Contract):
    zones: list[Zone] = Field(default_factory=list, max_length=20)


class ZoneState(ZoneDocument):
    confirmed: bool = False
    origin: Literal["user", "fixture", "unconfirmed"] = "unconfirmed"


class ZoneConfirmation(Contract):
    sha256: str
    origin: Literal["user", "fixture"]


def read_zone_state(root: Path) -> ZoneState:
    path = root / "zones/lanes.json"
    document = ZoneDocument.model_validate_json(path.read_text()) if path.exists() else ZoneDocument()
    receipt = root / "zones/confirmation.json"
    if document.zones and receipt.exists():
        confirmation = ZoneConfirmation.model_validate_json(receipt.read_text())
        if confirmation.sha256 == hashlib.sha256(path.read_bytes()).hexdigest():
            return ZoneState(zones=document.zones, confirmed=True, origin=confirmation.origin)
    # Older original fixture workspaces have exact generator geometry and a
    # provenance record, not human-reviewed real-world regions.
    provenance = root / "synthetic-provenance.json"
    if document.zones and not receipt.exists() and provenance.exists():
        value = json.loads(provenance.read_text())
        if value.get("generator") == "VisionApp original deterministic rectangle fixtures":
            return ZoneState(zones=document.zones, confirmed=True, origin="fixture")
    return ZoneState(zones=document.zones)


def save_zone_state(root: Path, zones: list[Zone], *, origin: Literal["user", "fixture"] = "user") -> ZoneState:
    if not zones or len({zone.id for zone in zones}) != len(zones):
        raise ValueError("Save at least one region with unique names")
    document = ZoneDocument(zones=zones)
    path = root / "zones/lanes.json"
    atomic_model(path, document)
    atomic_model(root / "zones/confirmation.json", ZoneConfirmation(
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), origin=origin))
    return ZoneState(zones=zones, confirmed=True, origin=origin)
