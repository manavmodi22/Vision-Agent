"""Model installation inventory, with explicit unverified inference status."""
from __future__ import annotations

import os
import platform
from pathlib import Path

from PIL import Image

from engine.capabilities.common import (
    app_license,
    code_provenance,
    evidence,
    file_evidence,
    now,
    package_evidence,
    small_hash,
)
from engine.models.fixture import PALETTE, detect_fixture
from engine.models.local_manifest import read_manifest
from engine.models.manager import list_models, model_directory
from spec.capabilities import (
    CapabilityHardware,
    CapabilityLicense,
    CapabilityManifest,
    CapabilityProvenance,
    CapabilityReadiness,
)


def model_catalog() -> list[CapabilityManifest]:
    result: list[CapabilityManifest] = []
    for record in list_models():
        identifier = str(record["id"])
        if identifier == "fixture-color-v1":
            result.append(_fixture())
            continue
        if identifier == "yolox-s-onnx-coco":
            result.append(_yolox())
            continue
        native = identifier == "apple-vision"
        local = identifier.startswith("local-")
        backend = str(record.get("backend", "unknown"))
        model_path = Path(str(record.get("path", model_directory() / identifier)))
        packages = [] if native else ["torch", "torchvision" if backend == "ssdlite320" else "transformers", "safetensors"]
        if identifier == "owlv2-base-patch16":
            packages.append("scipy")
        checks = [package_evidence(name) for name in packages]
        files = ["model.safetensors"] if backend == "ssdlite320" else ["config.json", "preprocessor_config.json", "model.safetensors"]
        if identifier == "owlv2-base-patch16":
            files.extend(["tokenizer_config.json", "vocab.json", "merges.txt"])
        if native:
            binary = os.environ.get("VISION_APP_BINARY", "")
            checks.extend([evidence("platform", "macOS", platform.system() == "Darwin", "Apple Vision requires macOS"),
                           file_evidence(Path(binary)) if binary else evidence("file", "VISION_APP_BINARY", False, "Native bridge is not configured")])
            installed = platform.system() == "Darwin"
            version = platform.mac_ver()[0] or None
        else:
            checks.extend(file_evidence(model_path / filename) for filename in files)
            installed = model_path.is_dir()
            version = None
        provenance = CapabilityProvenance(scope="registry_metadata", source_urls=[str(record["source"])] if record.get("source") else [],
            notes=["Registry metadata; current weights have not been content-verified by discovery."])
        if not native:
            for filename in ("config.json", "manifest.json"):
                digest = small_hash(model_path / filename)
                if digest:
                    provenance.hashes[filename] = digest
            revision_file = model_path / "VISIONAPP_REVISION.txt"
            try:
                if revision_file.is_file() and revision_file.stat().st_size <= 256:
                    version = revision_file.read_text().strip()
                    provenance.revision = version
            except (OSError, UnicodeError):
                checks.append(evidence("file", str(revision_file), False, "Revision metadata is unreadable; reinstall the trusted snapshot."))
        license_info = CapabilityLicense(identifier=str(record.get("license", "unverified")),
            code=str(record["license"]), weights=str(record.get("weights_license", record["license"])), status="declared")
        if record["license"] not in {"MIT", "Apache-2.0", "BSD-3-Clause architecture; project-trained weights", "macOS system framework"}:
            license_info.status = "policy_blocked"
            checks.append(evidence("adapter", "license policy", False, "Model license is unverified or not approved by the installed adapter policy."))
        if local:
            try:
                manifest = read_manifest(identifier, model_directory())
                provenance.scope, provenance.revision = "local_manifest", manifest.upstream_revision
                provenance.source_urls = [manifest.source]
                provenance.notes.extend(manifest.warnings)
                version = manifest.created_at
                if manifest.upstream_weights_sha256:
                    provenance.hashes["declared_upstream_weights"] = manifest.upstream_weights_sha256
                checks.append(evidence("adapter", identifier, True, "Local manifest validated; quality and current weights remain unverified"))
            except (OSError, ValueError) as error:
                checks.append(evidence("adapter", identifier, False, str(error)))
                license_info.status = "unverified"
        ready = bool(record.get("available")) and all(item.outcome == "pass" for item in checks)
        compatible = native and platform.system() == "Darwin" or not native
        availability = "installed" if installed else "available_to_install" if compatible else "unsupported"
        reason = "Prerequisites are present; run a bounded inference validation before promotion." if ready else "Missing or invalid prerequisites: " + ", ".join(item.subject for item in checks if item.outcome == "fail")
        result.append(CapabilityManifest.model_validate({
            "id": "model." + identifier, "name": record["name"], "kind": "model", "description": record.get("description", "Local detector"),
            "availability": availability, "implemented": compatible, "installation_ready": ready, "callable": False,
            "task_types": ["ocr", "barcode"] if native else ["detection", "training"] if backend == "rtdetr-v2-r18" else ["detection"],
            "version": version, "license": license_info, "provenance": provenance,
            "hardware": CapabilityHardware(platforms=["Darwin"] if native else ["Darwin", "Linux"],
                accelerators=["system-managed"] if native else ["cpu", "mps"] if backend != "ssdlite320" else ["cpu"],
                required_packages=packages, notes=["Memory and throughput are not estimated without measurement."]),
            "side_effects": ["read_images", "local_inference"], "install_method": "system_framework" if native else "local_training" if local else "manual_weights",
            "install_instructions": "Build the native bridge and configure VISION_APP_BINARY." if native else "Use reviewed project training; do not substitute arbitrary manifests." if local else f"Install the vision dependency extra and place the official local snapshot at {model_path}; downloads require separate approval.",
            "readiness": CapabilityReadiness(state="unchecked" if ready else "blocked" if compatible else "unsupported", reason=reason,
                checked_at=now(), evidence_scope="prerequisites", evidence=checks),
        }))
    return result


def _fixture() -> CapabilityManifest:
    passed = detect_fixture(Image.new("RGB", (8, 8), PALETTE["pallet"]), ["pallet"], .4)
    ok = len(passed) == 1 and passed[0].box == [0, 0, 1, 1]
    return CapabilityManifest(id="model.fixture-color-v1", name="Synthetic color fixture", kind="model",
        description="Original colored rectangles for software checks; not a warehouse detector.", availability="installed",
        implemented=True, installation_ready=True, callable=ok, task_types=["detection"], version="1",
        license=app_license(), provenance=code_provenance(Path(__file__).parents[1] / "models/fixture.py"),
        hardware=CapabilityHardware(platforms=["Darwin", "Linux", "Windows"], accelerators=["cpu"], required_packages=["numpy", "Pillow"]),
        side_effects=["read_images", "local_inference"], install_method="bundled",
        readiness=CapabilityReadiness(state="ready" if ok else "blocked", checked_at=now(), evidence_scope="inference_smoke",
            reason="Tiny CPU fixture self-test passed; no real-world accuracy implied." if ok else "Fixture self-test failed",
            evidence=[evidence("inference_smoke", "8x8 synthetic pallet rectangle", ok, "Executed the actual fixture adapter on this host.")]))


def _yolox() -> CapabilityManifest:
    from engine.provisioning.plans import make_plan
    from engine.provisioning.registry import YOLOX
    from engine.provisioning.state import current_health, installation_matches

    plan = make_plan(YOLOX)
    installed = installation_matches(YOLOX)
    receipt = current_health(YOLOX.model_id)
    checks = [evidence("package", package, plan.runtime_snapshot["package:" + package] != "missing",
        "Installed distribution metadata; executable imports are checked by bounded smoke",
        {"version": plan.runtime_snapshot["package:" + package]}) for package in YOLOX.packages]
    checks.extend(evidence("file", artifact.filename,
        (Path(plan.target_directory) / artifact.filename).is_file(),
        "The installer verifies the reviewed exact byte size and SHA256 before installation")
        for artifact in YOLOX.artifacts)
    ready = installed and not plan.blockers
    if receipt:
        checks.append(evidence("inference_smoke", "Generated black 640x640 RGB image", True,
            "Executed the pinned adapter on this host; no accuracy or throughput claim",
            {"receipt_id": receipt.id, "elapsed_s": receipt.elapsed_s,
             "execution_identity_hash": receipt.execution_identity_hash}))
    reason = ("Current identity-bound black-image inference passed; evaluate on reviewed project data before promotion."
        if receipt else "; ".join(plan.blockers) if plan.blockers else
        "Installed artifacts are verified; bounded execution validation has not passed on this runtime."
        if installed else "Review the pinned installation plan, then explicitly approve download and validation.")
    return CapabilityManifest(id="model." + YOLOX.model_id, name=YOLOX.name, kind="model",
        description="Closed COCO vocabulary detector using the official pinned ONNX release and CPUExecutionProvider.",
        availability="installed" if installed else "available_to_install", implemented=True,
        installation_ready=ready, callable=bool(receipt and ready), task_types=["detection"], version=YOLOX.revision,
        license=plan.license,
        provenance=CapabilityProvenance(scope="registry_metadata", revision=YOLOX.revision,
            source_urls=[artifact.source_url for artifact in YOLOX.artifacts],
            hashes={artifact.filename: artifact.expected_sha256 for artifact in YOLOX.artifacts},
            notes=["Hashes identify the reviewed official artifacts; receipt validity also binds current installed bytes/runtime."]),
        hardware=plan.hardware, side_effects=["read_images", "local_inference"],
        install_method="reviewed_provisioning", install_instructions="Open the reviewed provisioning plan; downloads and smoke inference require an explicit human action.",
        readiness=CapabilityReadiness(state="ready" if receipt and ready else "unchecked" if ready else "blocked",
            reason=reason, checked_at=now(), evidence_scope="inference_smoke" if receipt else "prerequisites", evidence=checks))
