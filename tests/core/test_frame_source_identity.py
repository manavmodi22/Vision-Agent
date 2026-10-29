"""File previews bind the bytes actually decoded; live pixels do not invent files."""
import hashlib
from pathlib import Path

import pytest
from PIL import Image

from engine.compiler import CompiledPipeline, compile_pipeline
from engine.runtime import executor
from engine.runtime.values import ExecutionState
from spec.models import FrameResult, PipelineSpec


def sampled() -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "Source identity software test",
        "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [{"id": "sample", "type": "frame_sample", "in": {"frames": "$inputs.source"}}]})


def test_file_preview_records_unchanged_source_bytes(tmp_path: Path) -> None:
    path = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "blue").save(path)
    result = executor.execute_frame(compile_pipeline(sampled(), tmp_path), path, 0, ExecutionState())
    assert result.source_image_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_file_mutation_during_inference_discards_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "blue").save(path)
    original = executor.execute_image

    def changed(compiled: CompiledPipeline, image: Image.Image, image_path: str,
                timestamp: float, state: ExecutionState) -> FrameResult:
        Image.new("RGB", (100, 80), "red").save(path)
        return original(compiled, image, image_path, timestamp, state)

    monkeypatch.setattr(executor, "execute_image", changed)
    with pytest.raises(ValueError, match="changed during inference"):
        executor.execute_frame(compile_pipeline(sampled(), tmp_path), path, 0, ExecutionState())


def test_in_memory_preview_has_no_file_identity(tmp_path: Path) -> None:
    result = executor.execute_image(compile_pipeline(sampled(), tmp_path), Image.new("RGB", (10, 8)),
        "live/camera", 0, ExecutionState())
    assert result.source_image_sha256 is None
