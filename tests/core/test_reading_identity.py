"""Reading evidence must expire when its native implementation changes."""
from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest
from PIL import Image

import engine.adapters.legacy as executor
import engine.blocks.reading_identity as identity
from engine.blocks.reading import VisionReading
from engine.eval import EvaluationError, evaluate, spec_hash
from engine.eval.reading import reading_errors
from engine.service import WorkspaceService
from spec.models import Annotation, EvalDataset, PipelineSpec


def pipeline(kind: str = "ocr", source: str = "media") -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Reading identity fixture",
        "inputs": {"source": {"type": "image_folder", "path": source}},
        "blocks": [{"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "read", "type": kind, "in": {"image": "$sample.frame"}}],
        "eval": {"metric": "text_accuracy", "target": 1.0}})


@pytest.fixture
def bridge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "native-bridge"
    path.write_bytes(b"bridge-v1")
    monkeypatch.setenv("VISION_APP_BINARY", str(path))
    return path


def change_identity(change: str, bridge: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if change == "bridge":
        before = bridge.stat()
        bridge.write_bytes(b"bridge-v2")
        # A file stat cache must not disguise changed executable content.
        os.utime(bridge, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == "macos":
        monkeypatch.setattr(platform, "mac_ver", lambda: ("changed-macos", ("", "", ""), ""))
    elif change == "kernel":
        monkeypatch.setattr(platform, "release", lambda: "changed-kernel")
    elif change == "policy":
        monkeypatch.setattr(identity, "READING_REQUEST_POLICY_VERSION", "changed-policy")
    else:
        raise AssertionError(f"Unknown fixture change: {change}")


@pytest.mark.parametrize("kind", ["ocr", "barcode"])
@pytest.mark.parametrize("change", ["bridge", "macos", "kernel", "policy"])
def test_reading_hash_changes_but_detection_hash_does_not(
    kind: str, change: str, bridge: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    reading = pipeline(kind)
    detector = pipeline().model_copy(deep=True)
    detector.blocks[-1].type = "detect"
    detector.blocks[-1].params = {"model": "fixture-color-v1", "classes": ["pallet"]}
    before_reading, before_detector = spec_hash(reading), spec_hash(detector)
    change_identity(change, bridge, monkeypatch)
    assert spec_hash(reading) != before_reading
    assert spec_hash(detector) == before_detector


def test_missing_bridge_is_bound_without_claiming_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VISION_APP_BINARY", raising=False)
    before = spec_hash(pipeline())
    assert identity.native_reading_identity()["bridge_sha256"] == "missing"
    path = tmp_path / "new-bridge"
    path.write_bytes(b"bridge-v1")
    monkeypatch.setenv("VISION_APP_BINARY", str(path))
    assert spec_hash(pipeline()) != before
    assert identity.native_reading_identity()["identity_scope"] == "system_framework_versioned"


@pytest.mark.parametrize("change", ["bridge", "macos"])
def test_saved_reading_score_and_approval_are_stale_after_identity_change(
    change: str, bridge: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def read_fixture(_image: Image.Image) -> VisionReading:
        return VisionReading(texts=["ABC-990"])
    monkeypatch.setattr(executor, "read_native", read_fixture)
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("Synthetic reading evidence test", "labels")
    service.demo(project.id)
    labels = service.annotations(project.id)
    for annotation in labels.annotations:
        annotation.detections = []
        annotation.expected_texts = ["ABC-990"]
    service.save_annotations(project.id, labels)
    service.save_candidates(project.id, [pipeline()], "Read fixture text")
    score = service.evaluate(project.id)
    assert score.passed and score.sample_count >= 10
    # Explicit approval belongs only to this temporary synthetic test project.
    service.deploy(project.id, 0, True, "Isolated software-only local trial", approval_scope="local_trial")
    change_identity(change, bridge, monkeypatch)
    assert score.spec_hash != spec_hash(pipeline(), service.root(project.id))
    with pytest.raises(ValueError, match="Evaluate this"):
        service.deploy(project.id, 0, True)
    with pytest.raises(ValueError, match="Approval is stale"):
        service.run(project.id, max_frames=1)
    assert service.events(project.id) == []


def test_bridge_change_during_evaluation_never_issues_score(
    bridge: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "text.png"
    Image.new("RGB", (80, 30), "white").save(image)
    def changed_reader(_image: Image.Image) -> VisionReading:
        change_identity("bridge", bridge, monkeypatch)
        return VisionReading(texts=["ABC-990"])
    monkeypatch.setattr(executor, "read_native", changed_reader)
    labels = EvalDataset(id="synthetic", annotations=[
        Annotation(image_path="text.png", expected_texts=["ABC-990"], reviewed=True)])
    with pytest.raises(EvaluationError, match="changed while"):
        evaluate(pipeline(source="."), labels, tmp_path)


def test_native_homoglyph_error_is_retained_in_exactness_and_cer() -> None:
    result = reading_errors(["XABC-990Y"], ["\u0425ABC-990Y"])
    assert not result.exact_match
    assert result.character_edits == 1
    assert result.word_edits == 1
