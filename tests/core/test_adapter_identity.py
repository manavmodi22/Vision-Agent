"""Content-bound model state, including changes hidden from an mtime-only cache."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

import engine.adapters.identity as identity
import engine.adapters.legacy as legacy
from engine.adapters.contracts import DetectionRequest
from engine.adapters.registry import InferenceAborted, run_inference
from engine.eval.hashes import spec_hash
from engine.models.artifacts import model_content_fingerprint
from engine.models.local_manifest import LocalDetectorManifest
from spec.models import Detection, PipelineSpec


@pytest.fixture
def model_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(identity, "execution_provider", lambda adapter: "cpu")
    model = tmp_path / "owlv2-base-patch16"
    model.mkdir()
    for name, content in {"model.safetensors": b"weights-v1", "config.json": b'{"revision":1}',
                          "preprocessor_config.json": b'{"size":1}', "vocab.json": b'{"a":1}',
                          "merges.txt": b"tokens-v1"}.items():
        (model / name).write_bytes(content)
    return model


def model_spec() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Identity test",
        "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "f", "type": "frame_sample", "in": {"frames": "$inputs.source"}},
                   {"id": "d", "type": "detect_open_vocab", "params": {"model": "owlv2-base-patch16", "classes": ["person"]},
                    "in": {"image": "$f.frame"}}]})


def overwrite_same_stat(path: Path) -> None:
    before = path.stat()
    original = path.read_bytes()
    path.write_bytes(original.replace(b"1", b"2"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size and path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("filename", ["model.safetensors", "config.json", "preprocessor_config.json", "vocab.json", "merges.txt"])
def test_every_consumed_artifact_invalidates_identity_and_score_despite_restored_mtime(model_files: Path, filename: str) -> None:
    request = DetectionRequest(model_id="owlv2-base-patch16", classes=["person"], min_conf=.2)
    before = identity.resolve_execution_identity(request)
    assert before.adapter_id == "owlv2" and before.capability_id == "model.owlv2-base-patch16"
    score_binding = spec_hash(model_spec())
    cache_key = model_content_fingerprint(request.model_id)
    overwrite_same_stat(model_files / filename)
    assert identity.resolve_execution_identity(request).identity_hash != before.identity_hash
    assert spec_hash(model_spec()) != score_binding
    assert model_content_fingerprint(request.model_id) != cache_key


def test_changed_model_is_rejected_before_or_after_adapter_call(model_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = DetectionRequest(model_id="owlv2-base-patch16", classes=["person"], min_conf=.2)
    before = identity.resolve_execution_identity(request)
    def changed_during_call(*args: object) -> list[object]:
        overwrite_same_stat(model_files / "model.safetensors")
        return []
    monkeypatch.setattr(legacy, "detect", changed_during_call)
    with pytest.raises(InferenceAborted, match="changed while running"):
        run_inference(Image.new("RGB", (20, 20)), request, expected_identity_hash=before.identity_hash)
    def must_not_run(*args: object) -> list[object]:
        raise AssertionError("Stale compiled model was invoked")
    monkeypatch.setattr(legacy, "detect", must_not_run)
    with pytest.raises(InferenceAborted, match="changed after compilation"):
        run_inference(Image.new("RGB", (20, 20)), request, expected_identity_hash=before.identity_hash)


def test_request_configuration_changes_identity_without_substituting_model(model_files: Path) -> None:
    first = DetectionRequest(model_id="owlv2-base-patch16", classes=["person"], min_conf=.2)
    second = first.model_copy(update={"min_conf": .5})
    assert identity.resolve_execution_identity(first).identity_hash != identity.resolve_execution_identity(second).identity_hash
    assert identity.resolve_execution_identity(first).model_id == first.model_id
    with pytest.raises(ValueError, match="No implemented adapter"):
        identity.resolve_execution_identity(first.model_copy(update={"model_id": "yolox-unknown"}))


def test_changed_adapter_source_requires_process_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    identity._code_hash("fixture-color-v1")
    monkeypatch.setattr(identity, "content_hash", lambda path: "a" * 64)
    with pytest.raises(ValueError, match="restart the engine"):
        identity._code_hash("fixture-color-v1")


def test_owl_cache_uses_verified_content_not_file_timestamps(model_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real loader cache with stub model construction, never inference."""
    import transformers

    from engine.models import owlv2

    loads: list[str] = []
    class FakeModel:
        def to(self, device: str) -> FakeModel:
            return self
        def eval(self) -> FakeModel:
            return self
    def construct(*args: object, **kwargs: object) -> FakeModel:
        loads.append((model_files / "model.safetensors").read_text())
        return FakeModel()
    monkeypatch.setattr(owlv2, "validate_model", lambda model: None)
    monkeypatch.setattr(transformers.Owlv2Processor, "from_pretrained", lambda *a, **k: object())
    monkeypatch.setattr(transformers.Owlv2ForObjectDetection, "from_pretrained", construct)
    owlv2._load.cache_clear()
    try:
        first = model_content_fingerprint("owlv2-base-patch16")
        owlv2._load(str(model_files), first, "cpu")
        owlv2._load(str(model_files), first, "cpu")
        assert loads == ["weights-v1"]
        owlv2._load(str(model_files), first, "mps")  # Stub .to(); no device kernel is run.
        assert loads == ["weights-v1", "weights-v1"]
        overwrite_same_stat(model_files / "model.safetensors")
        with pytest.raises(ValueError, match="changed while"):
            # A cache miss with a stale expected fingerprint must fail before load.
            owlv2._load.__wrapped__(str(model_files), first, "cpu")
        owlv2._load(str(model_files), model_content_fingerprint("owlv2-base-patch16"), "cpu")
        assert loads == ["weights-v1", "weights-v1", "weights-v2"]
    finally:
        owlv2._load.cache_clear()


@pytest.mark.parametrize(("model_id", "backend"), [
    ("rtdetr-v2-r18", "rtdetr-v2-r18"), ("local-rtdetr-test", "rtdetr-v2-r18"),
    ("local-ssdlite-test", "ssdlite320"),
])
def test_existing_registered_families_keep_model_choice_and_manifest_binding(
    model_id: str, backend: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(identity, "execution_provider", lambda adapter: "cpu")
    path = tmp_path / model_id
    path.mkdir()
    (path / "model.safetensors").write_bytes(b"synthetic-weight-test")
    (path / "config.json").write_text('{"id2label":{"0":"person"}}')
    (path / "preprocessor_config.json").write_text('{}')
    if model_id.startswith("local-"):
        manifest = LocalDetectorManifest.model_validate({"id": model_id, "backend": backend,
            "classes": ["person"], "training_hash": "train", "evaluation_hash": "eval", "created_at": "test",
            "training_samples": 10, "epochs_completed": 1, "steps": 1, "final_loss": 1})
        (path / "manifest.json").write_text(manifest.model_dump_json())
    calls: list[str] = []
    detection = Detection(label="person", confidence=.7, box=[.1, .2, .5, .8])
    def recorded_detection(image: Image.Image, model: str, classes: list[str], min_conf: float) -> list[Detection]:
        calls.append(model)
        assert classes == ["person"] and min_conf == .2
        return [detection]
    monkeypatch.setattr(legacy, "detect", recorded_detection)
    request = DetectionRequest(model_id=model_id, classes=["person"], min_conf=.2)
    result = run_inference(Image.new("RGB", (20, 20)), request)
    assert calls == [model_id] and result.identity.model_id == model_id
    assert result.identity.adapter_id == backend
    assert result.detections[0].box == (.1, .2, .5, .8)
    if model_id.startswith("local-"):
        before = result.identity.identity_hash
        assert "manifest.json" in result.identity.artifact_hashes
        (path / "manifest.json").write_text(manifest.model_copy(update={"classes": ["carton"]}).model_dump_json())
        assert identity.resolve_execution_identity(request).identity_hash != before
