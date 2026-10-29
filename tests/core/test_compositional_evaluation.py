"""Composed-output software diagnostics cannot qualify unscored branches."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from engine.adapters import legacy
from engine.blocks.reading import VisionReading
from engine.eval import evaluate
from engine.eval.protocol import (
    acceptance_blockers,
    freeze_protocol,
    protocol_dataset,
    read_configuration,
    save_configuration,
)
from engine.eval.recipe import RECIPE_VERSION, task_signature, unscored_behaviors
from engine.media import import_paths
from engine.models.artifacts import canonical_hash
from engine.models.fixture import PALETTE
from engine.store.repository import atomic_model
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment, EvidencePolicy
from spec.models import Annotation, BlockSpec, Detection, EvalDataset, PipelineSpec


def reader(*kinds: str) -> PipelineSpec:
    return PipelineSpec(name="Composed software reader", inputs={"source": {"type": "image_folder", "path": "media"}},
        blocks=[BlockSpec(id="sample", type="frame_sample", inputs={"frames": "$inputs.source"})]
        + [BlockSpec(id=f"read{i}", type=kind, inputs={"image": "$sample.frame"}) for i, kind in enumerate(kinds)],
        eval={"metric": "text_accuracy", "target": 1})


@pytest.fixture
def scaffold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, EvalDataset]:
    source = tmp_path / "inputs"
    source.mkdir()
    files = []
    for i in range(2):
        image = source / f"software-{i}.png"
        Image.new("RGB", (100, 100), (0, 0, 80 * i)).save(image)
        files.append(str(image))
    root = tmp_path / "project"
    images = import_paths(files, root / "media")
    dataset = EvalDataset(id="software-only", annotations=[Annotation(image_path=path, reviewed=True,
        expected_texts=["ABC"]) for path in images])
    atomic_model(root / "annotations.json", dataset)
    bridge = tmp_path / "mocked-native"
    bridge.write_bytes(b"Mocked reader for software contract tests only")
    monkeypatch.setenv("VISION_APP_BINARY", str(bridge))
    monkeypatch.setattr(legacy, "read_native", lambda image: VisionReading(texts=["ABC"], barcodes=["ABC"]))
    return root, dataset


def configure(root: Path, dataset: EvalDataset) -> None:
    config = read_configuration(root, dataset)
    save_configuration(root, dataset, EvaluationConfigurationUpdate(expected_revision=config.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, scene_group="dev" if i == 0 else "accept",
            split="validation" if i == 0 else "acceptance", data_origin="real") for i, row in enumerate(config.images)],
        policy=EvidencePolicy(intended_use="Software tests only", independent_group_basis="Generated distinct test inputs",
            coverage_rationale="Narrow software gate test, not model quality", required_acceptance_groups=["accept"])))


@pytest.mark.parametrize("second_kind", ["ocr", "barcode"])
def test_union_success_cannot_qualify_a_failed_reader_branch(
    scaffold: tuple[Path, EvalDataset], monkeypatch: pytest.MonkeyPatch, second_kind: str,
) -> None:
    root, dataset = scaffold
    candidate = reader("ocr", second_kind)
    configure(root, dataset)
    calls = 0

    def partial(image: Image.Image) -> VisionReading:
        nonlocal calls
        calls += 1
        return VisionReading(texts=["ABC"] if calls % 2 else [], barcodes=[])

    monkeypatch.setattr(legacy, "read_native", partial)
    with pytest.raises(ValueError, match="per-branch quality gates"):
        freeze_protocol(root, dataset, [candidate], [0], "acceptance")
    assert calls == 0  # Refuse acceptance before any held-out inference.
    protocol = freeze_protocol(root, dataset, [candidate], [0], "validation")
    score = evaluate(candidate, dataset, root, protocol=protocol)
    assert calls == 2 and score.text_accuracy == 1 and score.passed
    assert not score.promotion_eligible
    assert any("deduplicated union" in warning for warning in score.warnings)
    assert any("per-branch quality gates" in reason for reason in score.evidence_reasons)


@pytest.mark.parametrize("metric", ["text_accuracy", "count_mae"])
def test_mixed_output_primary_gate_is_only_a_diagnostic(
    scaffold: tuple[Path, EvalDataset], monkeypatch: pytest.MonkeyPatch, metric: str,
) -> None:
    root, dataset = scaffold
    data = dataset.model_copy(deep=True)
    data.annotations = data.annotations[:1]
    data.annotations[0].detections = [Detection(label="pallet", confidence=1, box=[.1, .1, .3, .3])]
    if metric == "count_mae":
        image = Image.new("RGB", (100, 100))
        ImageDraw.Draw(image).rectangle((10, 10, 29, 29), fill=PALETTE["pallet"])
        image.save(data.annotations[0].image_path)
        monkeypatch.setattr(legacy, "read_native", lambda image: VisionReading(texts=[], barcodes=[]))
    candidate = reader("ocr")
    candidate.blocks.append(BlockSpec(id="det", type="detect", params={"model": "fixture-color-v1",
        "classes": ["pallet"]}, inputs={"image": "$sample.frame"}))
    candidate.eval = type(candidate.eval)(metric=metric, target=0 if metric == "count_mae" else 1)
    score = evaluate(candidate, data, root)
    assert score.passed and not score.promotion_eligible
    assert (score.text_accuracy, score.recall) == ((1, 0) if metric == "text_accuracy" else (0, 1))
    assert any("one output task" in warning for warning in score.warnings)
    assert any("one output task" in reason for reason in score.evidence_reasons)
    assert any("one output task" in reason for reason in acceptance_blockers(root, data, [candidate], 0))


def test_single_reader_acceptance_still_works(scaffold: tuple[Path, EvalDataset]) -> None:
    root, dataset = scaffold
    configure(root, dataset)
    candidate = reader("ocr")
    assert not unscored_behaviors(candidate)
    assert not acceptance_blockers(root, dataset, [candidate], 0)
    protocol = freeze_protocol(root, dataset, [candidate], [0], "acceptance")
    score = evaluate(candidate, dataset, root, protocol=protocol)
    assert score.passed and score.promotion_eligible


def comparison(sink: bool = True) -> PipelineSpec:
    candidate = reader("ocr", "barcode")
    candidate.blocks.append(BlockSpec(id="match", type="match", params={"expected": "ABC", "mode": "exact"},
                                      inputs={"text": "$read0.text"}))
    if sink:
        candidate.blocks.append(BlockSpec(id="out", type="sink_event", inputs={"event": "$match.event"}))
    return candidate


def test_comparison_and_event_output_have_distinct_tasks(scaffold: tuple[Path, EvalDataset]) -> None:
    root, dataset = scaffold
    no_events, emitted = comparison(False), comparison()
    assert task_signature(no_events, root) != task_signature(emitted, root)
    with pytest.raises(ValueError, match="share output task"):
        freeze_protocol(root, dataset, [no_events, emitted], [0, 1])


@pytest.mark.parametrize("sink", [False, True])
def test_reader_to_comparison_association_is_part_of_task(scaffold: tuple[Path, EvalDataset], sink: bool) -> None:
    root, _ = scaffold
    candidate = comparison(sink)
    barcode_check = candidate.model_copy(deep=True)
    next(block for block in barcode_check.blocks if block.type == "match").inputs["text"] = "$read1.text"
    assert task_signature(candidate, root) != task_signature(barcode_check, root)


def test_event_routing_and_multiplicity_are_bound(scaffold: tuple[Path, EvalDataset]) -> None:
    root, _ = scaffold
    base = comparison()
    twice = base.model_copy(deep=True)
    twice.blocks.append(BlockSpec(id="out2", type="sink_event", inputs={"event": "$match.event"}))
    routed = base.model_copy(deep=True)
    routed.blocks[-1].params["alert"] = "webhook:configured-target"
    assert len({task_signature(candidate, root) for candidate in [base, twice, routed]}) == 3


def test_ids_order_and_preprocessing_do_not_prevent_same_task_experiments(scaffold: tuple[Path, EvalDataset]) -> None:
    root, dataset = scaffold
    original = comparison()
    alternative = original.model_copy(deep=True)
    alternative.blocks.extend([
        BlockSpec(id="crop", type="crop", params={"box": [0, 0, .5, 1]}, inputs={"image": "$sample.frame"}),
        BlockSpec(id="resize", type="resize", params={"width": 200, "height": 200}, inputs={"image": "$crop.image"})])
    next(block for block in alternative.blocks if block.id == "read0").inputs["image"] = "$resize.image"
    for block in alternative.blocks:
        block.id = "renamed_" + block.id
        block.inputs = {port: reference if reference.startswith("$inputs.") else "$renamed_" + reference[1:]
                        for port, reference in block.inputs.items()}
    alternative.blocks.reverse()
    assert task_signature(original, root) == task_signature(alternative, root)
    protocol = freeze_protocol(root, dataset, [original, alternative], [0, 1])
    assert protocol.candidates[0].spec_hash != protocol.candidates[1].spec_hash


def test_historical_recipe_remains_readable_but_cannot_score(scaffold: tuple[Path, EvalDataset]) -> None:
    root, dataset = scaffold
    current = freeze_protocol(root, dataset, [reader("ocr")], [0])
    assert current.recipe_version == RECIPE_VERSION == "reviewed-images-v3"
    old = current.model_copy(update={"recipe_version": "reviewed-images-v2"})
    old = old.model_copy(update={"protocol_hash": canonical_hash(old.model_dump(mode="json", exclude={"protocol_hash"}))})
    atomic_model(root / "evaluation/protocols" / f"{old.id}.json", old)
    with pytest.raises(ValueError, match="recipe changed"):
        protocol_dataset(root, dataset, old)


def test_vlm_text_is_also_an_independent_branch() -> None:
    candidate = reader("ocr")
    # Scope classification itself does not compile or contact a model server.
    candidate.blocks.append(BlockSpec(id="judge", type="vlm_judge", inputs={"image": "$sample.frame"}))
    reasons = unscored_behaviors(candidate)
    assert any("one output task" in reason for reason in reasons)
    assert any("per-branch quality gates" in reason for reason in reasons)
