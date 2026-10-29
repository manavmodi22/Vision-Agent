"""Pinned artifact/session/routing checks using explicit synthetic ORT stubs."""
from __future__ import annotations

import hashlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import engine.models as models
from engine.adapters.contracts import DetectionRequest
from engine.adapters.identity import resolve_execution_identity
from engine.adapters.registry import run_inference
from engine.models import artifacts, manager, yolox
from engine.models.yolox_config import COCO_CLASSES, MODEL_ID
from engine.models.yolox_ops import FloatArray


@pytest.fixture
def installed_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path))
    path = tmp_path / MODEL_ID
    path.mkdir()
    weights = b"synthetic-ONNX-test-weights"
    (path / "model.onnx").write_bytes(weights)
    # Test-only pin: never a callable actual ONNX checkpoint or quality evidence.
    for module in (artifacts, yolox):
        monkeypatch.setattr(module, "MODEL_BYTES", len(weights))
        monkeypatch.setattr(module, "MODEL_SHA256", hashlib.sha256(weights).hexdigest())
    yolox._load.cache_clear()
    yield path
    yolox._load.cache_clear()


class FakeSession:
    def __init__(self) -> None:
        self.disabled = False
        self.calls = 0
        self.providers = ["CPUExecutionProvider"]
        self.input_shape = [1, 3, 640, 640]
        self.output_shape = [1, 8400, 85]
        self.output = np.zeros((1, 8400, 85), dtype=np.float32)
        self.output[0, 0, :6] = [20, 20, 2, 2, .8, .9]

    def disable_fallback(self) -> None:
        self.disabled = True

    def get_providers(self) -> list[str]:
        return self.providers

    def get_inputs(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="images", shape=self.input_shape, type="tensor(float)")]

    def get_outputs(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(name="output", shape=self.output_shape, type="tensor(float)")]

    def run(self, names: list[str] | None, values: dict[str, FloatArray]) -> list[object]:
        assert names is None and set(values) == {"images"}
        assert values["images"].shape == (1, 3, 640, 640)
        self.calls += 1
        return [self.output]


@pytest.fixture
def stub_ort(monkeypatch: pytest.MonkeyPatch) -> list[FakeSession]:
    sessions: list[FakeSession] = []
    def construct(content: bytes, sess_options: SimpleNamespace, providers: list[str]) -> FakeSession:
        assert content == b"synthetic-ONNX-test-weights"
        assert providers == ["CPUExecutionProvider"]
        assert sess_options.intra_op_num_threads == 4
        assert sess_options.inter_op_num_threads == 1
        assert sess_options.execution_mode == "sequential"
        session = FakeSession()
        sessions.append(session)
        return session
    fake = SimpleNamespace(SessionOptions=SimpleNamespace, InferenceSession=construct,
                           ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
                           get_available_providers=lambda: ["CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)
    return sessions


def test_cpu_session_is_content_keyed_reused_and_no_fallback(
    installed_stub: Path, stub_ort: list[FakeSession],
) -> None:
    image = Image.new("RGB", (640, 480))
    first = yolox.detect_yolox(image, ["person"], .2)
    assert len(first) == 1 and first[0].confidence == pytest.approx(.72)
    assert yolox.detect_yolox(image, ["person"], .2) == first
    assert len(stub_ort) == 1 and stub_ort[0].disabled and stub_ort[0].calls == 2
    assert yolox._load.cache_info().maxsize == 1
    # Configuration/provenance content also invalidates a loaded session.
    (installed_stub / "provenance.json").write_text('{"receipt":"v2"}')
    assert yolox.detect_yolox(image, ["person"], .2) == first
    assert len(stub_ort) == 2


def test_changed_weights_with_restored_mtime_cannot_reuse_cached_session(
    installed_stub: Path, stub_ort: list[FakeSession],
) -> None:
    image = Image.new("RGB", (640, 480))
    yolox.detect_yolox(image, ["person"], .2)
    path = installed_stub / "model.onnx"
    before = path.stat()
    path.write_bytes(path.read_bytes().replace(b"weights", b"mutated"))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(manager.ModelUnavailable, match="pinned official"):
        yolox.detect_yolox(image, ["person"], .2)
    assert len(stub_ort) == 1 and stub_ort[0].calls == 1


@pytest.mark.parametrize("classes", [["forklift"], ["pallet"], ["Person"], []])
def test_unsupported_classes_fail_before_loading(classes: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object) -> str:
        raise AssertionError("Unknown class reached model loading")
    monkeypatch.setattr(yolox, "model_content_fingerprint", forbidden)
    with pytest.raises(manager.ModelUnavailable, match="exact COCO"):
        yolox.detect_yolox(Image.new("RGB", (20, 20)), classes, .2)


@pytest.mark.parametrize("threshold", [-1., 2., float("nan"), float("inf")])
def test_bad_threshold_rejected(threshold: float) -> None:
    with pytest.raises(manager.ModelUnavailable, match="confidence threshold"):
        yolox.detect_yolox(Image.new("RGB", (20, 20)), ["person"], threshold)


@pytest.mark.parametrize("problem", ["provider", "input_shape", "output_shape"])
def test_wrong_session_contract_fails_closed(
    installed_stub: Path, stub_ort: list[FakeSession], problem: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = sys.modules["onnxruntime"]
    original = fake.InferenceSession  # type: ignore[attr-defined]
    def wrong(*args: object, **kwargs: object) -> FakeSession:
        session: FakeSession = original(*args, **kwargs)
        if problem == "provider":
            session.providers.append("CoreMLExecutionProvider")
        elif problem == "input_shape":
            session.input_shape = [1, 3, 320, 320]
        else:
            session.output_shape = [1, 2100, 85]
        return session
    monkeypatch.setattr(fake, "InferenceSession", wrong)
    with pytest.raises(manager.ModelUnavailable, match="requires CPU|contract"):
        yolox.detect_yolox(Image.new("RGB", (640, 480)), ["person"], .2)


def test_artifact_and_common_envelope_bind_exact_adapter_provider_and_parameters(
    installed_stub: Path, stub_ort: list[FakeSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(models, "validate_model", lambda model: None)
    request = DetectionRequest(model_id=MODEL_ID, classes=["person"], min_conf=.2)
    before = resolve_execution_identity(request)
    assert before.adapter_id == "yolox-onnx" and before.provider == "CPUExecutionProvider"
    assert before.capability_id == "model." + MODEL_ID
    assert before.artifact_hashes["model.onnx"] == artifacts.MODEL_SHA256
    result = run_inference(Image.new("RGB", (640, 480)), request)
    assert len(result.detections) == 1 and result.identity == before
    assert result.input_size == (640, 480) and result.timing.total_ms >= 0
    assert result.timing.inference_ms is None  # No invented component timing.
    assert resolve_execution_identity(request.model_copy(update={"min_conf": .3})).identity_hash != before.identity_hash
    (installed_stub / "provenance.json").write_text('{"review":"test"}')
    assert resolve_execution_identity(request).identity_hash != before.identity_hash


def test_model_catalog_distinguishes_verified_files_from_inference(
    installed_stub: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = manager.importlib.util.find_spec
    monkeypatch.setattr(manager.importlib.util, "find_spec",
                        lambda name: object() if name in {"onnxruntime", "cv2", "numpy"} else original(name))
    entry = next(item for item in manager.list_models() if item["id"] == MODEL_ID)
    assert entry["available"] is True and entry["backend"] == "yolox-onnx"
    assert entry["classes"] == list(COCO_CLASSES) and entry["estimated_fps"] is None
    (installed_stub / "model.onnx").write_bytes(b"wrong model")
    assert next(item for item in manager.list_models() if item["id"] == MODEL_ID)["available"] is False


def test_mutation_during_inference_discards_result(
    installed_stub: Path, stub_ort: list[FakeSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", (640, 480))
    yolox.detect_yolox(image, ["person"], .2)
    original = stub_ort[0].run
    def changed(names: list[str] | None, values: dict[str, FloatArray]) -> list[object]:
        result = original(names, values)
        (installed_stub / "provenance.json").write_text('{"changed":true}')
        return result
    monkeypatch.setattr(stub_ort[0], "run", changed)
    with pytest.raises(manager.ModelUnavailable, match="changed while"):
        yolox.detect_yolox(image, ["person"], .2)


def test_runtime_failure_is_actionable_without_provider_retry(
    installed_stub: Path, stub_ort: list[FakeSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", (640, 480))
    yolox.detect_yolox(image, ["person"], .2)
    calls = 0
    def failed(*args: object) -> list[object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic CPU error")
    monkeypatch.setattr(stub_ort[0], "run", failed)
    with pytest.raises(manager.ModelUnavailable, match="no fallback was used: synthetic CPU error"):
        yolox.detect_yolox(image, ["person"], .2)
    assert calls == 1 and len(stub_ort) == 1


def test_cpu_provider_unavailable_does_not_construct_another_provider(
    installed_stub: Path, stub_ort: list[FakeSession], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.modules["onnxruntime"], "get_available_providers", lambda: ["CoreMLExecutionProvider"])
    with pytest.raises(manager.ModelUnavailable, match="CPUExecutionProvider is unavailable"):
        yolox.detect_yolox(Image.new("RGB", (640, 480)), ["person"], .2)
    assert stub_ort == []
