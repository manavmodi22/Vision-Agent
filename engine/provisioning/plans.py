"""Create immutable review documents from coded recipes and current host facts."""
from __future__ import annotations

import platform
import uuid

from engine.models.artifacts import canonical_hash
from engine.provisioning.registry import Recipe
from engine.provisioning.state import (
    installation_hash,
    installation_matches,
    runtime_snapshot,
    target_path,
)
from engine.store.models import now
from spec.capabilities import CapabilityHardware, CapabilityLicense, CapabilityReadiness
from spec.provisioning import ProvisioningPlan


def plan_hash(plan: ProvisioningPlan) -> str:
    return canonical_hash(plan.model_dump(mode="json", exclude={"plan_hash"}))


def make_plan(recipe: Recipe) -> ProvisioningPlan:
    snapshot = runtime_snapshot(recipe)
    blockers = []
    if platform.system() not in recipe.platforms:
        blockers.append("This reviewed recipe supports only " + ", ".join(recipe.platforms))
    missing = [package for package in recipe.packages if snapshot["package:" + package] == "missing"]
    if missing:
        blockers.append("Required packaged runtime dependencies are missing: " + ", ".join(missing))
    existing = None
    installed = False
    try:
        existing = installation_hash(recipe)
        installed = installation_matches(recipe)
        if existing is not None and not installed:
            blockers.append("Existing target differs from the reviewed artifacts. It was preserved; move it aside explicitly before creating a new install plan.")
    except (ValueError, OSError) as error:
        blockers.append(str(error))
    timestamp = now()
    plan = ProvisioningPlan(id=uuid.uuid4().hex, plan_hash="0" * 64, created_at=timestamp,
        model_id=recipe.model_id, capability_id="model." + recipe.model_id, name=recipe.name,
        action="validate" if installed else "install", artifacts=list(recipe.artifacts),
        license=CapabilityLicense(identifier="Apache-2.0", code="Apache-2.0",
            weights="Official repository Apache-2.0 declaration; a separate asset license was not found in the inspected release", status="declared",
            notes=["License scope is the official repository declaration, not independent legal verification of the weights.",
                   "Weights are fetched from the pinned official release; this app does not redistribute weights."]),
        source_revision=recipe.revision, target_directory=str(target_path(recipe)),
        total_download_bytes=0 if installed else sum(item.expected_bytes for item in recipe.artifacts),
        max_duration_s=recipe.max_duration_s,
        hardware=CapabilityHardware(platforms=list(recipe.platforms), accelerators=["cpu"],
            required_packages=list(recipe.packages), estimated_disk_bytes=sum(item.expected_bytes for item in recipe.artifacts),
            notes=["CPUExecutionProvider only. A bounded black-image smoke proves execution, not accuracy or production throughput."]),
        readiness=CapabilityReadiness(state="blocked" if blockers else "unchecked", checked_at=timestamp,
            evidence_scope="prerequisites", reason="; ".join(blockers) if blockers else
                "Host prerequisites are present. Installation and inference will run only after explicit approval."),
        blockers=blockers, runtime_snapshot=snapshot, existing_installation_hash=existing)
    return plan.model_copy(update={"plan_hash": plan_hash(plan)})
