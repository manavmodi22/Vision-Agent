"""Bounded loopback metadata probes. Listing models never proves image capability."""
from __future__ import annotations

import asyncio
import json

import httpx
from pydantic import JsonValue, TypeAdapter

from engine.capabilities.common import evidence, now
from engine.store.models import Settings
from spec.capabilities import (
    CapabilityHardware,
    CapabilityLicense,
    CapabilityManifest,
    CapabilityProvenance,
    CapabilityReadiness,
)

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


async def server_capability(settings: Settings, *, vision: bool) -> CapabilityManifest:
    base_url = settings.vlm_url if vision else settings.model_url
    selected = settings.vlm_model if vision else settings.planner_model
    checks = []
    metadata: dict[str, JsonValue] = {}
    if selected:
        try:
            async with asyncio.timeout(3), httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", base_url + "/models") as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 256 * 1024:
                            raise ValueError("Model metadata exceeds 256 KiB")
                    parsed = JSON_OBJECT.validate_python(json.loads(body))
            rows = parsed.get("data")
            if not isinstance(rows, list):
                raise ValueError("Model server did not return a model list")
            found = next((item for item in rows if isinstance(item, dict) and item.get("id") == selected), None)
            if found is not None:
                metadata = dict(found)
            checks.append(evidence("server_metadata", base_url + "/models", found is not None,
                "Selected alias is advertised; weights identity, tool use and image support are not verified.",
                {"selected_model": selected, "advertised": metadata}))
        except (httpx.HTTPError, ValueError, TimeoutError) as error:
            checks.append(evidence("server_metadata", base_url + "/models", False, f"Local metadata probe failed: {error}"))
    else:
        checks.append(evidence("server_metadata", base_url, False, "Choose and load a local model in Settings."))
    ready = all(check.outcome == "pass" for check in checks)
    return CapabilityManifest(id="model.configured-vlm" if vision else "model.configured-planner",
        name=("Configured vision model" if vision else "Configured planner") + (": " + selected if selected else ""),
        kind="model", description="Configured loopback model service; metadata is not inference validation.",
        availability="installed", implemented=True, installation_ready=ready, callable=False,
        task_types=["visual_judgement"] if vision else ["planning"],
        license=CapabilityLicense(identifier=str(metadata.get("license", "unverified")), status="unverified",
            notes=["Model alias does not establish weights provenance or distribution rights."]),
        provenance=CapabilityProvenance(scope="server_metadata", notes=["Endpoint: " + base_url, "Selected model: " + selected]),
        hardware=CapabilityHardware(platforms=["loopback service"], notes=["Server hardware and memory are not inspected."]),
        side_effects=["local_model_request"], install_method="manual_weights",
        install_instructions="Configure a compatible local model server and select its actual loaded model ID. No model is installed by this API.",
        readiness=CapabilityReadiness(state="unchecked" if ready else "blocked", checked_at=now(), evidence_scope="metadata", evidence=checks,
            reason="Server advertises the selected model; validate actual structured output and image support before promotion." if ready else "The configured local model is not currently advertised."))
