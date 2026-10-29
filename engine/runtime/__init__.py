"""Bounded pipeline runner. Calls remain synchronous for background job workers."""
from __future__ import annotations

import time
from itertools import islice
from pathlib import Path

from engine.blocks.params import FrameSampleParams
from engine.compiler import compile_pipeline
from engine.runtime.executor import execute_frame
from engine.runtime.media import source_frames
from engine.runtime.values import ExecutionState
from spec.models import EvalDataset, PipelineSpec, RunResult


def run_pipeline(spec: PipelineSpec, project_root: Path, max_frames: int = 50) -> RunResult:
    if not 1 <= max_frames <= 10000:
        raise ValueError("max_frames must be between 1 and 10000")
    started = time.perf_counter()
    compiled = compile_pipeline(spec, project_root)
    sampling = [p.fps for p in compiled.params.values() if isinstance(p, FrameSampleParams)]
    if sampling and len(set(sampling)) > 1:
        raise ValueError("Version 0.1 requires the same sampling rate across branches")
    state = ExecutionState()
    source = spec.inputs["source"]
    labels_path = project_root / "annotations.json"
    reserved: set[Path] = set()
    if labels_path.exists():
        from engine.eval.protocol import reserved_acceptance_paths
        dataset = EvalDataset.model_validate_json(labels_path.read_text())
        reserved = {(project_root / path).resolve() for path in reserved_acceptance_paths(project_root, dataset)}
    limit = 10000 if reserved and source.type == "image_folder" else max_frames
    selected = list(islice(((path, timestamp) for path, timestamp in
                    source_frames(source, project_root, sampling[0] if sampling else 2, limit)
                    if path.resolve() not in reserved), max_frames))
    if not selected:
        raise ValueError("No development images are available; reserved acceptance images are excluded from previews and ordinary runs")
    if labels_path.exists():
        from engine.eval.protocol import mark_usage
        mark_usage(project_root, [str(path.resolve()) for path, _ in selected], "preview_or_run")
    frames = [execute_frame(compiled, path, timestamp, state if source.type == "video_file" else ExecutionState())
              for path, timestamp in selected]
    return RunResult(frames=frames, elapsed_s=time.perf_counter() - started,
                     warnings=list(compiled.warnings))


__all__ = ["run_pipeline"]
