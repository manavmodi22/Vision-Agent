"""Protocol integration with real fixture pixels or explicitly mocked model inference."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agent.build_orchestrator import select_candidate
from agent.templates import build_template
from engine.api import create_app
from engine.live.approval import inspect as inspect_live_approval
from engine.models.artifacts import canonical_hash
from engine.service import WorkspaceService
from spec.inference import ExecutionIdentity
from spec.models import Detection, FrameResult, PipelineSpec


def fixture_service(root: Path) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(root)
    project = service.create_project("Protocol fixture", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1"), "Count pallets")
    return service, project.id


def test_fixture_numeric_pass_needs_explicit_local_trial_and_never_sends_alerts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service, identifier = fixture_service(tmp_path)
    score = service.evaluate(identifier)
    assert score.passed and not score.promotion_eligible and score.evidence_scope == "sample"
    assert score.protocol_id and score.protocol_hash
    with pytest.raises(ValueError, match="Promotion requires"):
        service.deploy(identifier, 0, True)
    with pytest.raises(ValueError, match="explicit reason"):
        service.deploy(identifier, 0, True, approval_scope="local_trial")
    with pytest.raises(ValueError, match="explicit user"):
        service.deploy(identifier, 0, False, "Supervised local software trial", approval_scope="local_trial")
    result = service.deploy(identifier, 0, True, "Supervised local software trial", approval_scope="local_trial")
    assert result["trial_limits"] == {"max_frames_per_run": 500, "max_live_duration_s": 3600}
    assert service.get_project(identifier).approval_scope == "local_trial"
    def no_delivery(*args: object, **kwargs: object) -> None:
        raise AssertionError("Local trials must not enqueue external delivery")
    monkeypatch.setattr("engine.alerts.service.AlertService.enqueue_events", no_delivery)
    run = service.run(identifier, max_frames=2)
    assert len(run.frames) == 2 and any("external alert delivery is disabled" in text for text in run.warnings)
    assert all(event.payload["approval_scope"] == "local_trial" for event in service.events(identifier))
    assert all(event.payload["evaluation_protocol_id"] == score.protocol_id for event in service.events(identifier))
    assert inspect_live_approval(service, identifier, 0, False)[0].approval_scope == "local_trial"
    with pytest.raises(ValueError, match="bounded"):
        service.run(identifier, max_frames=501)


def test_legacy_result_and_approval_read_but_cannot_authorize_new_run(tmp_path: Path) -> None:
    service, identifier = fixture_service(tmp_path)
    score = service.evaluate(identifier)
    project = service.get_project(identifier)
    project.evaluations = [score.model_copy(update={"protocol_id": None, "protocol_hash": None, "evidence_scope": "legacy"})]
    service.repository.save(project)
    with pytest.raises(ValueError, match="current protocol"):
        service.deploy(identifier, 0, True, "Legacy evidence is only historical", approval_scope="local_trial")
    assert service.get_project(identifier).evaluations[0].evidence_scope == "legacy"


def test_comparison_requires_one_protocol_and_candidate_change_invalidates_all_scores(tmp_path: Path) -> None:
    service, identifier = fixture_service(tmp_path)
    first = service.candidate(identifier, 0)
    second = first.model_copy(deep=True)
    second.name = "Alternative threshold"
    next(block for block in second.blocks if block.type == "detect").params["min_conf"] = 1.0
    service.save_candidates(identifier, [first, second], "Count pallets")
    protocol = service.freeze_evaluation(identifier)
    scores = [service.evaluate(identifier, index, protocol.id) for index in range(2)]
    assert select_candidate(scores) == 0
    different = service.evaluate(identifier, 1)
    with pytest.raises(ValueError, match="exact frozen"):
        select_candidate([scores[0], different])
    project = service.get_project(identifier)
    project.candidates[1].eval.target = 0.25
    service.repository.save(project)
    with pytest.raises(ValueError, match="candidate changed"):
        service.validate_evaluation(identifier, scores[0])


def test_api_configuration_cas_preserves_labels_and_invalidates_trial(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)
    service = app.state.service
    project = service.create_project("CAS fixture", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1"), "Count pallets")
    service.evaluate(project.id)
    service.deploy(project.id, 0, True, "Local software check only", approval_scope="local_trial")
    from agent.machine import AgentConflict
    from engine.builds.store import BuildStore
    from engine.platform.store import PlatformStore
    build_store = BuildStore(service)
    build_record = build_store.create(project.id, "Count pallets")
    platform = PlatformStore(service)
    before_snapshot = platform.snapshot(project.id, service.get_project(project.id).candidates)
    before = service.annotations(project.id).model_dump_json()
    url = f"/projects/{project.id}/evaluation/config"
    config = client.get(url).json()
    request = {"expected_revision": config["revision"], "assignments": [],
               "policy": {"intended_use": "Check one scene", "independent_group_basis": "", "coverage_rationale": "", "required_acceptance_groups": []}}
    assert client.put(url, json=request).status_code == 200
    assert client.put(url, json=request).status_code == 409
    assert service.annotations(project.id).model_dump_json() == before
    assert platform.snapshot(project.id, service.get_project(project.id).candidates) != before_snapshot
    with pytest.raises(AgentConflict, match="changed"):
        build_store.assert_current(build_record)
    assert service.get_project(project.id).deployment_id is None
    with pytest.raises(ValueError, match="Approve deployment"):
        service.run(project.id)


def _mock_model(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Software-only inference; these fixtures are not evidence of detector quality."""
    import engine.compiler as compiler
    import engine.eval as evaluation
    import engine.eval.hashes as hashes
    import engine.runtime as runtime
    from engine.adapters.contracts import InferenceRequest
    from engine.compiler import CompiledPipeline
    from engine.runtime.values import ExecutionState

    calls: list[str] = []
    def identity(request: InferenceRequest) -> ExecutionIdentity:
        return ExecutionIdentity(capability_id="model." + request.model_id, model_id=request.model_id,
            adapter_id="software-test", identity_scope="local_artifacts_verified", artifact_hashes={"test": "a" * 64},
            adapter_code_sha256="b" * 64, runtime_manifest_sha256="c" * 64, system_identity={"scope": "mocked software test"},
            provider="mock", config_sha256=canonical_hash(request.model_dump(mode="json")), identity_hash="d" * 64)
    def frame(compiled: CompiledPipeline, path: Path, timestamp: float, state: ExecutionState) -> FrameResult:
        calls.append(str(path))
        return FrameResult(image_path=str(path), detections=[Detection(label="person", confidence=.9, box=[.2, .2, .5, .5])], counts={"all": 1})
    monkeypatch.setattr(compiler, "validate_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(compiler, "trained_classes", lambda _: None)
    monkeypatch.setattr(compiler, "resolve_execution_identity", identity)
    monkeypatch.setattr(hashes, "resolve_execution_identity", identity)
    monkeypatch.setattr(evaluation, "execute_frame", frame)
    monkeypatch.setattr(runtime, "execute_frame", frame)
    monkeypatch.setattr("engine.runtime.autolabel.execute_frame", frame)
    return calls


def test_positive_fresh_import_reserve_review_acceptance_and_exact_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _mock_model(monkeypatch)
    app = create_app(tmp_path / "workspace")
    service = app.state.service
    client = TestClient(app)
    project = service.create_project("Mocked independent acceptance workflow", "custom")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = []
    for index in range(20):
        path = inputs / f"sample-{index}.png"
        Image.new("RGB", (32, 24), (index * 10, 80, 150)).save(path)
        paths.append(str(path))
    service.import_media(project.id, paths[:10])
    candidate = PipelineSpec.model_validate({"name": "Count person", "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "sample", "type": "frame_sample", "params": {"fps": 2}, "in": {"frames": "$inputs.source"}},
                   {"id": "det", "type": "detect", "params": {"model": "owlv2-base-patch16", "classes": ["person"], "min_conf": .2}, "in": {"image": "$sample.frame"}},
                   {"id": "count", "type": "count_per_zone", "params": {}, "in": {"dets": "$det.dets"}}],
        "eval": {"set": "reviewed-v1", "metric": "count_mae", "target": .5}})
    service.save_candidates(project.id, [candidate], "Count people")
    service.preview(project.id)
    development_calls = len(calls)
    imported = client.post(f"/projects/{project.id}/media", json={"paths": paths[10:]})
    assert imported.status_code == 200 and len(calls) == development_calls
    config_url = f"/projects/{project.id}/evaluation/config"
    config = client.get(config_url).json()
    first_ten = {str(Path(path).relative_to(service.root(project.id))) for path in service.get_project(project.id).media[:10]}
    assignments = [{"image_path": row["image_path"], "scene_group": "development" if row["image_path"] in first_ten else "reserved",
                    "split": "validation" if row["image_path"] in first_ten else "acceptance", "data_origin": "real"} for row in config["images"]]
    configured = client.put(config_url, json={"expected_revision": config["revision"], "assignments": assignments,
        "policy": {"intended_use": "Software test of declared scope", "independent_group_basis": "Separate declared imported sources in this test",
                   "coverage_rationale": "One explicitly required scene group; no generalization claim", "required_acceptance_groups": ["reserved"]}})
    assert configured.status_code == 200, configured.text
    labels = service.annotations(project.id)
    assert not any(row.reviewed for row in labels.annotations)
    for row in labels.annotations:
        row.reviewed = True
        row.detections = [Detection(label="person", confidence=1, box=[.2, .2, .5, .5])]
    service.save_annotations(project.id, labels)
    root = service.root(project.id)
    reserved_paths = {str(root / row["image_path"]) for row in configured.json()["images"] if row["split"] == "acceptance"}
    service.preview(project.id)
    assert not reserved_paths.intersection(calls)
    validation = service.evaluate(project.id)
    assert validation.passed and not validation.promotion_eligible and validation.sample_count == 10
    with pytest.raises(ValueError, match="Promotion requires"):
        service.deploy(project.id, 0, True)
    record = app.state.builds.store.create(project.id, "Count people")
    record.view.selected_candidate_index = 0
    record.view.status, record.view.phase, record.view.next_action = "awaiting_review", "evidence", "configure_evaluation"
    record.view.evaluations = [validation]
    app.state.builds.store.save(record)
    readiness_url = f"/projects/{project.id}/evaluation/readiness?candidate_index=0"
    readiness = client.get(readiness_url).json()
    assert readiness["acceptance_available"], readiness
    acceptance_url = f"/projects/{project.id}/evaluation/acceptance"
    accepted = client.post(acceptance_url, json={"candidate_index": 0})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["passed"] and accepted.json()["promotion_eligible"]
    assert accepted.json()["evidence_scope"] == "acceptance"
    before_replay = len(calls)
    logs_before_replay = app.state.builds.store.get(project.id).view.log
    replay = client.post(acceptance_url, json={"candidate_index": 0})
    assert replay.json() == accepted.json() and len(calls) == before_replay
    assert app.state.builds.store.get(project.id).view.log == logs_before_replay
    current = client.get(readiness_url).json()
    assert current["acceptance_replay_available"] and not current["acceptance_available"] and current["acceptance_blockers"] == []
    build = client.get(f"/projects/{project.id}/build").json()
    assert build["acceptance_evaluation"] == accepted.json()
    assert build["evaluations"][0]["protocol_id"] == validation.protocol_id
    assert build["next_action"] == "approve_deployment" and service.events(project.id) == []
    approved = client.post(f"/projects/{project.id}/deploy", json={"candidate_index": 0, "approved": True, "approval_scope": "promotion"})
    assert approved.status_code == 200, approved.text
    assert service.approved_deployment(project.id, 0).protocol_id == accepted.json()["protocol_id"]
    changed = candidate.model_copy(deep=True)
    changed.blocks[1].params["min_conf"] = .3
    service.update_candidate(project.id, 0, changed, candidate)
    rejected = client.post(acceptance_url, json={"candidate_index": 0})
    assert rejected.status_code == 400 and "fresh" in rejected.text
    if output := os.environ.get("VISION_PROTOCOL_NATIVE_FIXTURE_DIR"):
        folder = Path(output)
        folder.mkdir(parents=True, exist_ok=True)
        for name, payload in {"configuration": configured.json(), "readiness": current, "result": accepted.json(), "build-status": build}.items():
            (folder / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")


async def test_real_mcp_hides_and_preserves_reserved_annotations(tmp_path: Path) -> None:
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from engine.eval.protocol import read_configuration, save_configuration
    from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment

    service, identifier = fixture_service(tmp_path)
    root = service.root(identifier)
    labels = service.annotations(identifier)
    # Reserve four rows. This synthetic fixture may test isolation, never qualify
    # for promotion or claim independent real-world evidence.
    configuration = read_configuration(root, labels)
    chosen = configuration.images[:4]
    save_configuration(root, labels, EvaluationConfigurationUpdate(expected_revision=configuration.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, scene_group=f"reserved-{i}",
            split="acceptance", data_origin="synthetic") for i, row in enumerate(chosen)], policy=configuration.policy))
    reserved = {str(root / row.image_path) for row in chosen}
    parameters = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server", "--data-dir", str(tmp_path)])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            sampled = await session.call_tool("frames_sample", {"project_id": identifier, "limit": 50})
            assert not sampled.isError and sampled.structuredContent
            assert len(sampled.structuredContent["paths"]) == 12
            assert not reserved.intersection(sampled.structuredContent["paths"])
            preview = await session.call_tool("pipeline_run", {"project_id": identifier})
            assert not preview.isError and preview.structuredContent
            assert not reserved.intersection(frame["image_path"] for frame in preview.structuredContent["frames"])
            hidden_change = labels.model_copy(deep=True)
            hidden_change.annotations[0].detections = []
            blocked = await session.call_tool("eval_create", {"project_id": identifier, "dataset": hidden_change.model_dump(mode="json")})
            assert blocked.isError
            assert service.annotations(identifier) == labels
            catalog = await session.list_tools()
            assert not {"evaluation_configure", "acceptance_run", "source_verify"}.intersection(tool.name for tool in catalog.tools)
    after = read_configuration(root, labels)
    before_reasons = {row.image_path: row.exposure_reasons for row in configuration.images}
    assert all(row.exposure_reasons == before_reasons[row.image_path] for row in after.images if str(root / row.image_path) in reserved)
