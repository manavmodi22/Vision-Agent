"""Home's crop request creates real local evidence, without inventing no-storage support."""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from agent.contracts import PatternChoice, PlanDecision
from agent.decisions import compile_decision, require_complete_alert
from agent.event_intent import event_intent
from agent.task_validation import validate_event_values
from engine.models.fixture import PALETTE
from engine.service import WorkspaceService
from evals.run_custom_goals import GoalCase
from spec.models import Detection

HOME_EXAMPLE = "Find damaged cartons and save a crop for review."


def choice(threshold: int | None) -> PlanDecision:
    return PlanDecision(message="Test decision", choices=[PatternChoice(
        use_case="custom", objects=["damaged carton"], metric="recall", target=.9,
        count_threshold=threshold)])


@pytest.mark.parametrize("brief", [HOME_EXAMPLE,
    "Find damaged cartons and record a crop for review.",
    "Find damaged cartons and save a frame for review.",
    "Find damaged cartons and record frame evidence when one appears.",
    "Find damaged cartons and save a local event.",
    "Find damaged cartons and save a local event when one appears.",
    "Find damaged cartons and record local evidence when one appears."])
def test_crop_and_frame_evidence_require_a_presence_event(brief: str) -> None:
    intent = event_intent(brief)
    assert intent.requested and intent.comparison == (">=", 1)
    validate_event_values(choice(1), brief)
    with pytest.raises(ValueError, match="count >= 1"):
        validate_event_values(choice(None), brief)
    assert require_complete_alert(choice(1), brief).choices


@pytest.mark.parametrize("ending", ["Don't save crops.", "Do not record frames.",
    "Without saving crops or frames.", "Do not save evidence.", "No storage.",
    "Never store images."])
def test_no_storage_cannot_silently_be_accepted_as_no_event(ending: str) -> None:
    brief = "Count damaged cartons. " + ending
    for threshold in (None, 1):
        with pytest.raises(ValueError, match="disabling evidence storage is unsupported"):
            validate_event_values(choice(threshold), brief)
        with pytest.raises(ValueError, match="disabling evidence storage is unsupported"):
            require_complete_alert(choice(threshold), brief)
    validate_event_values(PlanDecision(message="Storage cannot be disabled.",
        questions=["Is preview-only use acceptable?"]), brief)


def test_crop_object_or_transformation_does_not_invent_recording() -> None:
    for brief in ("Find crops in a field.", "Crop the image and detect damaged cartons.",
                  "Count damaged cartons, no events or alerts."):
        assert not event_intent(brief).requested
        validate_event_values(choice(None), brief)


def test_home_example_approved_fixture_run_saves_real_crop(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Synthetic crop evidence regression", "custom")
    service.demo(project.id)
    dataset = service.annotations(project.id)
    first = dataset.annotations[0]
    with Image.open(first.image_path) as original:
        image = original.convert("RGB")
    ImageDraw.Draw(image).rectangle((30, 65, 99, 84), fill=PALETTE["damaged carton"])
    image.save(first.image_path)
    first.detections.append(Detection(label="damaged carton", confidence=1,
        box=[30 / 640, 65 / 400, 100 / 640, 85 / 400]))
    # Exact generated geometry remains explicitly synthetic; this is not human GT.
    provenance = service.root(project.id) / "synthetic-provenance.json"
    record = json.loads(provenance.read_text())
    record["test_augmentation"] = "One exact damaged-carton color rectangle at [30,65,100,85]"
    provenance.write_text(json.dumps(record))
    service.save_annotations(project.id, dataset)
    decision = choice(1)
    validate_event_values(decision, HOME_EXAMPLE)
    spec = compile_decision(decision, "media", "fixture-color-v1").candidates[0]
    assert not any(block.type == "zone_filter" for block in spec.blocks)
    assert any(block.type == "rule" and block.params["when"] == "count >= 1" for block in spec.blocks)
    assert any(block.type == "sink_event" for block in spec.blocks)
    service.save_candidates(project.id, [spec], HOME_EXAMPLE)
    preview = service.preview(project.id)
    assert preview.frames[0].events and service.events(project.id) == []
    with pytest.raises(ValueError, match="Approve deployment"):
        service.run(project.id, max_frames=1)
    assert service.evaluate(project.id).passed
    # Explicit approval belongs only to this isolated temporary generated fixture.
    service.deploy(project.id, 0, True)
    service.run(project.id, max_frames=1)
    evidence = service.events(project.id)
    crop = next(event for event in evidence if event.label == "damaged carton")
    assert crop.payload["synthetic"] and Path(crop.crop_path).is_file()
    with Image.open(crop.crop_path) as saved:
        assert saved.size == (70, 20)
        assert all(abs(a - b) <= 3 for a, b in zip(saved.convert("RGB").getpixel((35, 10)), PALETTE["damaged carton"], strict=True))
    assert any(event.payload["kind"] == "rule" for event in evidence)


def test_benchmark_preserves_original_24_and_adds_exact_home_example() -> None:
    cases = [GoalCase.model_validate(item) for item in json.loads(Path("evals/custom_goals.json").read_text())]
    original = json.loads(Path("artifacts/stronger-planner/custom-goals-7cf-original24.json").read_text())
    current = json.loads(Path("evals/custom_goals.json").read_text())
    assert len(cases) == 25 and current[:24] == original
    home = cases[-1]
    assert home.brief == HOME_EXAMPLE and home.required == ["sink_event"]
    assert home.expected["classes"] == ["damaged carton"]
    assert home.expected["rule"] == "count >= 1" and home.forbidden == ["zone_filter"]
