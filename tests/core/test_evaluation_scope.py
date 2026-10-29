"""Scoring follows the displayed detector output, while hashing all evidence."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from engine.compiler import compile_pipeline
from engine.eval import EvaluationError, dataset_hash, evaluate
from engine.models.fixture import PALETTE
from spec.models import Annotation, BlockSpec, Detection, EvalDataset, PipelineSpec


def example(root: Path) -> tuple[PipelineSpec, EvalDataset]:
    image = Image.new("RGB", (100, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 29, 29), fill=PALETTE["pallet"])
    draw.rectangle((60, 10, 79, 29), fill=PALETTE["carton"])
    image.save(root / "sample.png")
    dataset = EvalDataset(id="mixed", annotations=[Annotation(image_path="sample.png", reviewed=True,
        detections=[Detection(label="pallet", confidence=1, box=[.1, .1, .3, .3], zone="old-pallet-zone"),
                    Detection(label="carton", confidence=1, box=[.6, .1, .8, .3], zone="old-carton-zone")])])
    spec = PipelineSpec.model_validate({"name": "cartons", "inputs": {"source": {"type": "image_file", "path": "sample.png"}},
        "blocks": [{"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "det", "type": "detect", "params": {"model": "fixture-color-v1", "classes": ["carton"]},
                    "in": {"image": "$sample.frame"}}], "eval": {"metric": "recall", "target": 1}})
    return spec, dataset


@pytest.mark.parametrize("metric", ["precision", "recall", "count_mae"])
def test_scoring_ignores_unrequested_classes_but_hashes_all_labels(tmp_path: Path, metric: str) -> None:
    spec, dataset = example(tmp_path)
    spec.eval = type(spec.eval)(metric=metric, target=0 if metric == "count_mae" else 1)
    before = dataset.model_copy(deep=True)
    score = evaluate(spec, dataset, tmp_path)
    assert score.precision == score.recall == 1 and score.count_mae == 0 and score.passed
    assert dataset == before and score.dataset_hash == dataset_hash(dataset, tmp_path)
    # An unrelated ontology label cannot lower the score, but changing it must
    # invalidate the evidence hash used to approve deployment.
    dataset.annotations[0].detections[0].box = [.1, .1, .4, .4]
    changed = evaluate(spec, dataset, tmp_path)
    assert changed.dataset_hash != score.dataset_hash
    assert changed.precision == changed.recall == 1 and changed.count_mae == 0


@pytest.mark.parametrize("metric", ["precision", "recall"])
def test_no_selected_class_positives_is_an_explicit_failure(tmp_path: Path, metric: str) -> None:
    spec, dataset = example(tmp_path)
    spec.eval = type(spec.eval)(metric=metric, target=1)
    spec.blocks[1].params["classes"] = ["damaged carton"]
    with pytest.raises(EvaluationError, match="selected classes and zones"):
        evaluate(spec, dataset, tmp_path)


def zone_block(root: Path, owner: str = "det") -> BlockSpec:
    (root / "left.json").write_text('{"zones":[{"id":"left","polygon":[[0,0],[0.5,0],[0.5,1],[0,1]]}]}')
    return BlockSpec(id="left", type="zone_filter", params={"zones": "left.json"}, inputs={"dets": f"${owner}.dets"})


def test_no_selected_positives_inside_final_zones_is_an_explicit_failure(tmp_path: Path) -> None:
    spec, dataset = example(tmp_path)
    spec.blocks.append(zone_block(tmp_path))
    with pytest.raises(EvaluationError, match="selected classes and zones"):
        evaluate(spec, dataset, tmp_path)


@pytest.mark.parametrize("zone_is_final", [False, True])
def test_final_detection_branch_selects_only_its_classes_and_zone_ancestors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, zone_is_final: bool,
) -> None:
    import engine.eval as evaluation
    spec, dataset = example(tmp_path)
    selected = compile_pipeline(spec, tmp_path)
    other = spec.model_copy(deep=True)
    other.blocks[1].id = "other"
    other.blocks[1].params["classes"] = ["pallet"]
    other.blocks.append(zone_block(tmp_path, "other"))
    branch = compile_pipeline(other, tmp_path)
    sample, detector = selected.blocks
    _, old_detector, old_zone = branch.blocks
    ordered = (sample, old_detector, detector, old_zone) if zone_is_final else (sample, old_detector, old_zone, detector)
    # Multi-detector authoring remains rejected by the compiler. Construct a
    # typed execution plan to test the executor's established last-output rule.
    spec.blocks = list(ordered)
    compiled = replace(selected, spec=spec, blocks=ordered,
        params={**branch.params, **selected.params}, zones=branch.zones,
        inference_identities={**branch.inference_identities, **selected.inference_identities})
    monkeypatch.setattr(evaluation, "compile_pipeline", lambda candidate, root: compiled)
    score = evaluate(spec, dataset, tmp_path)
    assert score.precision == score.recall == 1 and score.count_mae == 0 and score.passed
    assert score.dataset_hash == dataset_hash(dataset, tmp_path)
