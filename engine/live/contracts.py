"""Native capture metadata and bounded live-session wire contracts."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from spec.models import Contract, FrameResult

CAPACITY_BYTES = 32 * 1024 * 1024
MAX_RETAINED_FRAMES = 240
MAX_RETAINED_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_RECORDINGS = 256
MAX_DURATION_S = 3600
IDLE_TIMEOUT_S = 300
SourceKind = Literal["camera", "screen_capture", "recorded_video"]
SessionState = Literal["running", "stopping", "stopped", "failed", "limit_reached"]


class LiveError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class StartRequest(Contract):
    candidate_index: int = Field(default=0, ge=0, strict=True)
    source_kind: SourceKind
    source_label: str = Field(min_length=1, max_length=200)
    preview_only: bool = False


class FrameRequest(Contract):
    sequence: int = Field(ge=1, strict=True)
    width: int = Field(ge=1, le=8192, strict=True)
    height: int = Field(ge=1, le=8192, strict=True)
    bytes_per_row: int = Field(ge=4, le=CAPACITY_BYTES, strict=True)
    timestamp_s: float = Field(ge=0)

    @model_validator(mode="after")
    def valid_buffer(self) -> FrameRequest:
        if self.bytes_per_row < self.width * 4 or self.bytes_per_row % 4:
            raise ValueError("BGRA row stride must be a multiple of four and at least width * 4")
        if self.bytes_per_row * self.height > CAPACITY_BYTES:
            raise ValueError("Frame exceeds the 32 MiB shared-memory capacity")
        return self


class LiveStatus(Contract):
    session_id: str
    project_id: str
    state: SessionState = "running"
    shared_memory_path: str
    capacity_bytes: int = CAPACITY_BYTES
    preview_only: bool
    source_kind: SourceKind
    source_label: str
    sample_fps: float
    processed_frames: int = 0
    last_sequence: int | None = None
    last_timestamp_s: float | None = None
    retained_frames: int = 0
    retained_bytes: int = 0
    max_retained_frames: int = MAX_RETAINED_FRAMES
    max_retained_bytes: int = MAX_RETAINED_BYTES
    max_total_bytes: int = MAX_TOTAL_BYTES
    max_duration_s: int = MAX_DURATION_S
    idle_timeout_s: int = IDLE_TIMEOUT_S
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class FrameResponse(Contract):
    session_id: str
    state: SessionState
    result: FrameResult
    processing_ms: float
    processed_frames: int
    retained_frames: int
    retained_bytes: int
