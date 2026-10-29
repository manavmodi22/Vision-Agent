"""Discovery cannot turn file presence, remote metadata or proposals into proof."""
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from engine.api.capability_routes import build_router
from engine.capabilities import build_catalog, validate_experiment_capabilities
from engine.capabilities.blocks import unsupported_catalog
from engine.capabilities.common import evidence
from engine.capabilities.models import model_catalog
from engine.capabilities.servers import server_capability
from engine.service import WorkspaceService
from engine.store.models import Settings
from spec.capabilities import CapabilityCatalog, CapabilityManifest


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceService:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "weights"))
    monkeypatch.delenv("VISION_APP_BINARY", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    return WorkspaceService(tmp_path / "workspace")


def test_missing_models_are_installable_but_not_ready(isolated: WorkspaceService) -> None:
    entries = {item.id: item for item in model_catalog()}
    for identifier in ("model.owlv2-base-patch16", "model.rtdetr-v2-r18"):
        item = entries[identifier]
        assert item.availability == "available_to_install" and item.implemented
        assert not item.installation_ready and not item.callable
        assert item.readiness.state == "blocked"
        with pytest.raises(ValueError, match="not ready"):
            validate_experiment_capabilities(isolated, [identifier])
    fixture = entries["model.fixture-color-v1"]
    assert fixture.callable and fixture.readiness.evidence_scope == "inference_smoke"
    validate_experiment_capabilities(isolated, [fixture.id, "block.detect", "block.match"])


def test_installed_checkpoint_metadata_is_not_an_inference_claim(isolated: WorkspaceService, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.capabilities.models as models
    from engine.models.manager import rtdetr_path
    path = rtdetr_path()
    path.mkdir(parents=True)
    for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
        (path / name).write_text(json.dumps({"id2label": {"0": "person"}}))
    (path / "VISIONAPP_REVISION.txt").write_text("test-revision")
    monkeypatch.setattr(models, "package_evidence", lambda name: evidence("package", name, True, "Test dependency metadata"))
    monkeypatch.setattr(models, "list_models", lambda: [{"id": "rtdetr-v2-r18", "name": "Test checkpoint", "available": True,
        "backend": "rtdetr-v2-r18", "license": "Apache-2.0", "path": str(path)}])
    item = model_catalog()[0]
    assert item.availability == "installed" and item.installation_ready
    assert not item.callable and item.readiness.state == "unchecked"
    assert item.version == "test-revision" and item.provenance.revision == "test-revision"
    assert item.provenance.hashes and "model.safetensors" not in item.provenance.hashes
    assert all(check.kind != "inference_smoke" for check in item.readiness.evidence)
    validate_experiment_capabilities(isolated, [item.id])
    (path / "VISIONAPP_REVISION.txt").write_bytes(b"\xff")
    assert not model_catalog()[0].installation_ready
    (path / "VISIONAPP_REVISION.txt").write_text("test-revision")
    (path / "preprocessor_config.json").unlink()
    with pytest.raises(ValueError, match="not ready"):
        validate_experiment_capabilities(isolated, [item.id])


def test_unsupported_families_never_become_callable(isolated: WorkspaceService) -> None:
    entries = {item.id: item for item in unsupported_catalog()}
    for identifier in ("model.sam3", "model.yolo", "model.paddleocr", "block.segment"):
        item = entries[identifier]
        assert item.availability == "unsupported" and not item.implemented and not item.callable
        assert item.install_method == "not_implemented" and item.readiness.reason
        with pytest.raises(ValueError, match="Unsupported capability"):
            validate_experiment_capabilities(isolated, [identifier])
        changed = item.model_dump(mode="json")
        changed["callable"] = True
        with pytest.raises(ValidationError):
            CapabilityManifest.model_validate(changed)


def test_corrupt_local_manifest_and_license_fail_closed(isolated: WorkspaceService, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.models.manager import model_directory
    path = model_directory() / "local-broken"
    path.mkdir(parents=True)
    (path / "manifest.json").write_text('{"id":"different"}')
    item = next(item for item in model_catalog() if item.id == "model.local-broken")
    assert item.availability == "installed" and not item.installation_ready and not item.callable
    assert any(check.outcome == "fail" for check in item.readiness.evidence)


@pytest.mark.parametrize("response", ["valid", "wrong-id", "oversized", "malformed", "offline"])
async def test_server_metadata_is_bounded_and_never_claims_smoke(response: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.capabilities.servers as servers
    original = httpx.AsyncClient
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1/models"
        if response == "offline":
            raise httpx.ConnectError("offline", request=request)
        if response == "oversized":
            return httpx.Response(200, content=b" " * (256 * 1024 + 1))
        if response == "malformed":
            return httpx.Response(200, json={"data": "not a list"})
        return httpx.Response(200, json={"data": [{"id": "vlm" if response == "valid" else "other", "license": "unverified"}]})

    monkeypatch.setattr(servers.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    item = await server_capability(Settings(vlm_model="vlm"), vision=True)
    assert item.installation_ready is (response == "valid")
    assert not item.callable and item.readiness.evidence_scope == "metadata"
    assert all(check.kind == "server_metadata" for check in item.readiness.evidence)
    assert len(calls) == 1


async def test_catalog_uses_real_mcp_schemas_without_invoking_tools(isolated: WorkspaceService) -> None:
    before = list(isolated.repository.projects_dir.iterdir())
    catalog = await build_catalog(isolated)
    entries = {item.id: item for item in catalog.capabilities}
    assert len(entries) == len(catalog.capabilities)
    assert {"block.detect", "tool.pipeline_run", "tool.media_import", "model.configured-vlm"} <= entries.keys()
    assert "project_id" in entries["tool.pipeline_run"].input_schema["properties"]
    assert "write_project" in entries["tool.media_import"].side_effects
    assert "dispatch_phase_authorized_tool" in entries["tool.agent_tool_call"].side_effects
    assert {"server.py", "durable.py", "builds.py"} <= entries["tool.pipeline_run"].provenance.hashes.keys()
    assert entries["tool.pipeline_run"].license.status == "unverified"
    assert entries["model.fixture-color-v1"].license.identifier == "Project source; license unspecified"
    assert not entries["model.configured-vlm"].installation_ready
    assert list(isolated.repository.projects_dir.iterdir()) == before
    assert not (isolated.repository.root / "traces/spans.jsonl").exists()
    assert CapabilityCatalog.model_validate(catalog.model_dump(mode="json")) == catalog


def test_catalog_route_returns_typed_wire_contract(isolated: WorkspaceService) -> None:
    app = FastAPI()
    app.include_router(build_router(isolated))
    response = TestClient(app).get("/capabilities")
    assert response.status_code == 200
    catalog = CapabilityCatalog.model_validate(response.json())
    assert catalog.schema_version == "0.1" and catalog.host["mps_available"] is None
    assert any(item.id == "model.fixture-color-v1" and item.callable for item in catalog.capabilities)
