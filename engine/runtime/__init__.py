"""Bounded pipeline runner. Calls remain synchronous for background job workers."""
from __future__ import annotations

import time
from pathlib import Path

from engine.blocks.params import FrameSampleParams
from engine.compiler import compile_pipeline
from engine.runtime.executor import execute_frame
from engine.runtime.media import source_frames
from engine.runtime.values import ExecutionState
from spec.models import PipelineSpec, RunResult


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
    frames = [execute_frame(compiled, path, timestamp, state if source.type == "video_file" else ExecutionState())
              for path, timestamp in source_frames(source, project_root, sampling[0] if sampling else 2, max_frames)]
    return RunResult(frames=frames, elapsed_s=time.perf_counter() - started,
                     warnings=list(compiled.warnings))


__all__ = ["run_pipeline"]
