"""Machine-readable capability discovery and bounded-experiment eligibility."""
import asyncio

from starlette.concurrency import run_in_threadpool

from engine.blocks.registry import REGISTRY
from engine.capabilities.blocks import block_catalog, unsupported_catalog
from engine.capabilities.common import host, now
from engine.capabilities.models import model_catalog
from engine.capabilities.servers import server_capability
from engine.capabilities.tools import tool_catalog
from engine.service import WorkspaceService
from spec.capabilities import CapabilityCatalog


async def build_catalog(service: WorkspaceService) -> CapabilityCatalog:
    settings = service.repository.settings()
    models, planner, vision, tools = await asyncio.gather(
        run_in_threadpool(model_catalog), server_capability(settings, vision=False),
        server_capability(settings, vision=True), tool_catalog(service))
    models.extend([planner, vision])
    capabilities = models + block_catalog(models) + tools + unsupported_catalog()
    return CapabilityCatalog(generated_at=now(), host=host(), capabilities=sorted(capabilities, key=lambda item: item.id))


def validate_experiment_capabilities(service: WorkspaceService, required_ids: list[str]) -> None:
    """Permit installed, unchecked adapters for validation, never claim promotion."""
    models = {item.id: item for item in model_catalog()}
    settings = service.repository.settings()
    for identifier in set(required_ids):
        if identifier in {"model.configured-planner", "model.configured-vlm"}:
            configured = settings.planner_model if identifier.endswith("planner") else settings.vlm_model
            if not configured:
                raise ValueError(f"Capability {identifier} is not configured; choose a local model first")
            continue  # Actual endpoint and identity are rechecked by the adapter before use.
        if identifier.startswith("block."):
            block = identifier.removeprefix("block.")
            if block not in REGISTRY:
                raise ValueError(f"Unsupported capability {identifier}; no executable block is registered")
            if block == "barcode":
                dependencies = ["model.apple-vision"]
            elif block == "ocr":
                dependencies = [key for key in required_ids if key in models and "ocr" in models[key].task_types]
                if not dependencies:
                    dependencies = ["model.apple-vision"]
            elif block == "detect_open_vocab":
                dependencies = [key for key in required_ids if key in models and "detection" in models[key].task_types]
                if not dependencies:
                    dependencies = ["model.owlv2-base-patch16"]
            elif block == "vlm_judge":
                if not settings.vlm_model:
                    raise ValueError("Configure a local vision model before validating block.vlm_judge")
                dependencies = []
            else:
                dependencies = []
            for dependency in dependencies:
                if dependency not in models:
                    raise ValueError(f"Capability {identifier} needs unavailable {dependency}")
                if not models[dependency].installation_ready:
                    raise ValueError(f"Capability {identifier} needs {dependency}: {models[dependency].readiness.reason}")
            continue
        item = models.get(identifier)
        if item is None or not item.implemented:
            raise ValueError(f"Unsupported capability {identifier}; register and validate its adapter first")
        if item.availability != "installed" or not item.installation_ready:
            raise ValueError(f"Capability {identifier} is not ready for validation: {item.readiness.reason}")


__all__ = ["build_catalog", "validate_experiment_capabilities"]
