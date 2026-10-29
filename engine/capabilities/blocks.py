"""Registry-backed tool capabilities; unsupported proposals cannot become callable."""
from pathlib import Path

from engine.blocks.registry import REGISTRY, block_schema
from engine.capabilities.common import app_license, code_provenance, evidence, now
from spec.capabilities import (
    CapabilityHardware,
    CapabilityLicense,
    CapabilityManifest,
    CapabilityProvenance,
    CapabilityReadiness,
)

TASKS = {"frame_sample": ["media"], "detect": ["detection"], "detect_open_vocab": ["detection"],
         "zone_filter": ["spatial_filter"], "count_per_zone": ["counting"], "rule": ["event_logic"],
         "sink_event": ["events"], "ocr": ["ocr"], "barcode": ["barcode"], "match": ["text_comparison"],
         "vlm_judge": ["visual_judgement"], "resize": ["image_transform"], "crop": ["image_transform"]}


def block_catalog(models: list[CapabilityManifest]) -> list[CapabilityManifest]:
    by_id = {item.id: item for item in models}
    result = []
    for name, definition in REGISTRY.items():
        dependencies = ["model.apple-vision"] if name in {"ocr", "barcode"} else ["model.configured-vlm"] if name == "vlm_judge" else ["model.owlv2-base-patch16"] if name == "detect_open_vocab" else []
        checks = [evidence("adapter", name, True, "Implemented registry contract; invocation still requires a valid graph and its inputs.")]
        ready = all(by_id[item].installation_ready for item in dependencies)
        learned = bool(dependencies) or name == "detect"
        state = "blocked" if not ready else "unchecked" if learned else "ready"
        contract = block_schema(name)
        result.append(CapabilityManifest.model_validate({
            "id": "block." + name, "name": name.replace("_", " ").title(), "kind": "tool",
            "description": definition.description, "availability": "installed", "implemented": True,
            "installation_ready": ready, "callable": state == "ready", "task_types": TASKS[name], "version": "0.1",
            "license": app_license(), "provenance": code_provenance(Path(__file__).parents[1] / "blocks/registry.py"),
            "hardware": CapabilityHardware(platforms=["Darwin"] if name in {"ocr", "barcode"} else ["host"],
                notes=["Detector/model hardware requirements are selected and checked during compilation."] if learned else []),
            "side_effects": ["local_inference"] if learned else ["emit_pipeline_events"] if name == "sink_event" else [],
            "dependencies": dependencies, "input_schema": {"params": contract["params"], "ports": contract["inputs"]},
            "output_schema": {"ports": contract["outputs"]}, "install_method": "bundled",
            "readiness": {"state": state, "checked_at": now(), "evidence_scope": "prerequisites", "evidence": checks,
                "reason": "Dependency prerequisites are missing." if not ready else "Adapter contract is implemented; the selected model needs an inference validation." if learned else "Implemented local operation; graph and input validation remain required."},
        }))
    return result


def unsupported_catalog() -> list[CapabilityManifest]:
    proposals: list[tuple[str, str, str, list[str], str]] = [
        ("model.sam3", "SAM 3", "model", ["instance_segmentation"], "No segmentation adapter or host smoke test is implemented; hardware compatibility and model terms require review."),
        ("model.yolo", "YOLO variants", "model", ["detection", "instance_segmentation"], "No YOLO adapter is installed. Select an exact implementation/weight variant and review its license before adding an adapter."),
        ("model.paddleocr", "PaddleOCR alternative", "model", ["ocr"], "No PaddleOCR adapter, supported-weight manifest or OCR benchmark is implemented."),
        ("block.segment", "Instance segmentation", "tool", ["instance_segmentation"], "No segmentation block or mask output contract exists in the runtime."),
        ("tool.web_search", "External source acquisition", "tool", ["source_acquisition"], "No external search/crawl tool or data-transfer policy is installed."),
    ]
    return [CapabilityManifest.model_validate({"id": identifier, "name": name, "kind": kind,
        "description": reason, "availability": "unsupported", "implemented": False, "installation_ready": False,
        "callable": False, "task_types": tasks, "license": CapabilityLicense(identifier="unverified"),
        "provenance": CapabilityProvenance(scope="proposal", notes=["Candidate family only; not an executable claim."]),
        "hardware": CapabilityHardware(notes=["Compatibility and resource use have not been measured by this app."]),
        "install_method": "not_implemented", "readiness": CapabilityReadiness(state="unsupported", reason=reason,
            checked_at=now(), evidence_scope="not_assessed")}) for identifier, name, kind, tasks, reason in proposals]
