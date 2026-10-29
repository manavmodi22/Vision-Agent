from pathlib import Path

import pytest
from PIL import Image

from agent.machine import AgentConflict, AgentState, Phase
from agent.mcp_client import connect_tools
from engine.builds.store import BuildStore
from engine.service import WorkspaceService
from spec.build import BuildContext


async def test_large_dataset_gets_bounded_unreviewed_subset_over_mcp(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Large synthetic sample", "custom")
    paths = []
    for index in range(51):
        image = tmp_path / f"source-{index}.png"
        Image.new("RGB", (16, 16), (index, 0, 0)).save(image)
        paths.append(str(image))
    service.import_media(project.id, paths)
    original = service.annotations(project.id)
    store = BuildStore(service)
    record = store.create(project.id, "Count objects")
    record.operation.state.phase = Phase.EVALUATE
    store.save(record)
    async with connect_tools(str(service.repository.root), AgentState()) as tools:
        await tools.bind_build(project.id, record.view.id)
        context = BuildContext.model_validate(await tools.call("build_prepare_review", {"project_id": project.id}))
        assert context.review_subset_created and context.evaluation_image_count == 10
        assert context.evaluation_reviewed_count == 0 and context.image_count == 51
        heldout = service.evaluation_annotations(project.id)
        again = BuildContext.model_validate(await tools.call("build_prepare_review", {"project_id": project.id}))
        assert not again.review_subset_created and service.evaluation_annotations(project.id) == heldout
    assert service.annotations(project.id) == original
    assert not any(row.reviewed for row in heldout.annotations)
    assert len(store.get(project.id).operation.calls) == 2


def test_active_build_conflict_and_changed_holdout_are_rejected(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Bounded build", "custom")
    service.demo(project.id)
    store = BuildStore(service)
    record = store.create(project.id, "Count pallets")
    with pytest.raises(AgentConflict, match="already running"):
        store.create(project.id, "Overwrite current build")
    record.operation.state.phase = Phase.EVALUATE
    store.save(record)
    holdout = service.root(project.id) / "active-holdout.json"
    holdout.write_text(service.annotations(project.id).model_dump_json())
    with pytest.raises(AgentConflict, match="changed"):
        store.start_call(project.id, record.view.id, "build_context", {"project_id": project.id})


def test_agent_cannot_invent_a_training_grant(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Explicit approval only", "custom")
    store = BuildStore(service)
    record = store.create(project.id, "Train a detector")
    record.view.phase = "training"
    record.view.selected_candidate_index = 0
    store.save(record)
    with pytest.raises(AgentConflict, match="human approval"):
        store.consume_training_approval(project.id, record.view.id, 0)


async def test_interrupted_training_resumes_at_evaluation_without_reusing_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.machine import EvaluationEvidence
    from agent.templates import build_template
    from engine.builds.manager import BuildManager
    from spec.build import BuildContinueRequest

    service = WorkspaceService(tmp_path)
    project = service.create_project("Resume training state", "custom")
    service.demo(project.id)
    candidate = build_template("custom", "media", "fixture-color-v1", classes=["pallet"])[0]
    next(block for block in candidate.blocks if block.type == "detect").params["min_conf"] = 1
    service.save_candidates(project.id, [candidate], "Count pallets")
    result = service.evaluate(project.id)
    assert not result.passed
    manager = BuildManager(service)
    record = manager.store.create(project.id, "Count pallets")
    record.operation.state.phase = Phase.EVALUATE
    record.operation.state.record_evaluation(EvaluationEvidence(spec_hash=result.spec_hash, dataset_hash=result.dataset_hash,
        passed=False, sample_count=result.sample_count, reviewed=True,
        protocol_id=result.protocol_id, protocol_hash=result.protocol_hash, promotion_eligible=False))
    record.operation.state.specialize(2)
    record.view.phase, record.view.status = "training", "interrupted"
    record.training_attempts = 1
    record.training_approved_hash = "old-approval"
    manager.store.save(record)
    spawned = []
    monkeypatch.setattr(manager, "_spawn", lambda value: spawned.append(value))
    status = await manager.continue_build(project.id, BuildContinueRequest())
    assert status.status == "running" and status.phase == "reviewing"
    resumed = manager.store.get(project.id)
    assert resumed.operation.state.phase == Phase.EVALUATE and resumed.training_approved_hash is None
    assert resumed.training_attempts == 1 and resumed.operation.state.budget.training_minutes == 2
    assert len(spawned) == 1 and not (service.root(project.id) / "jobs").exists()
