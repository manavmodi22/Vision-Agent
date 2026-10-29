"""Owned shared-memory ingress with independent temporal state per live session."""
from __future__ import annotations

import mmap
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock, Timeout
from PIL import Image

from engine.blocks.params import FrameSampleParams
from engine.compiler import CompiledPipeline, compile_pipeline
from engine.live import approval, persistence
from engine.live.contracts import (
    CAPACITY_BYTES,
    FrameRequest,
    FrameResponse,
    LiveError,
    LiveStatus,
    SessionState,
    StartRequest,
)
from engine.runtime.executor import execute_image
from engine.runtime.values import ExecutionState
from engine.service import WorkspaceService
from engine.store.repository import atomic_model
from spec.models import SourceSpec


@dataclass
class Session:
    status: LiveStatus
    index: int
    approved: approval.Approval
    compiled: CompiledPipeline
    mapping: mmap.mmap | None
    status_path: Path | None
    temporal: ExecutionState = field(default_factory=ExecutionState)
    lock: threading.RLock = field(default_factory=threading.RLock)
    busy: bool = False
    created: float = field(default_factory=time.monotonic)
    activity: float = field(default_factory=time.monotonic)


class LiveManager:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.lock = threading.RLock()
        self.sessions: dict[str, Session] = {}
        self.ingress = service.repository.root / ".live-ingress"
        self.lease = FileLock(service.repository.root / ".live-manager.lock", timeout=0, thread_local=False)
        self.owns_lease = False
        self.closed = False
        self.wake = threading.Event()
        self.worker: threading.Thread | None = None

    def _ensure_lease(self) -> None:
        if self.owns_lease:
            return
        try:
            self.lease.acquire()
        except Timeout as error:
            raise LiveError("Another engine owns live capture for this workspace", 409) from error
        self.owns_lease = True
        self.ingress.mkdir(mode=0o700, exist_ok=True)
        self.ingress.chmod(0o700)
        for path in self.ingress.glob("*.bgra"):
            path.unlink()
        for path in self.service.repository.projects_dir.glob("*/live/*/status.json"):
            status = LiveStatus.model_validate_json(path.read_text())
            if status.state in {"running", "stopping"}:
                status.state, status.error = "failed", "Engine restarted; capture interrupted"
                atomic_model(path, status)

    def _save_status(self, session: Session) -> None:
        if session.status_path:
            atomic_model(session.status_path, session.status)
            session.status_path.parent.chmod(0o700)
            session.status_path.chmod(0o600)

    def _finish(self, session: Session, state: SessionState, reason: str | None = None) -> None:
        session.status.state, session.status.error = state, reason
        if session.mapping is not None:
            session.mapping.close()
            session.mapping = None
        Path(session.status.shared_memory_path).unlink(missing_ok=True)
        self._save_status(session)

    def start(self, project_id: str, request: StartRequest) -> LiveStatus:
        with self.lock:
            if self.closed:
                raise LiveError("Live capture manager is shut down", 410)
            self._ensure_lease()
            if sum(session.status.state == "running" for session in self.sessions.values()) >= 2:
                raise LiveError("At most two live capture sessions can run at once", 409)
            with self.service.repository.lock:
                approved, _ = approval.inspect(self.service, project_id, request.candidate_index, request.preview_only)
                if not request.preview_only:
                    persistence.ensure_capacity(self.service)
                root = self.service.root(project_id)
                # Capture supplies timestamped images directly; retain original spec hash
                # for approval, while enabling the video executor's temporal semantics.
                execution = approved.candidate.model_copy(deep=True)
                execution.inputs["source"] = SourceSpec(type="video_file", path="native-live-ingress")
                compiled = compile_pipeline(execution, root)
            fps = next((params.fps for params in compiled.params.values() if isinstance(params, FrameSampleParams)), 2.0)
            identifier = uuid.uuid4().hex
            path = self.ingress / f"{identifier}.bgra"
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.ftruncate(descriptor, CAPACITY_BYTES)
                mapping = mmap.mmap(descriptor, CAPACITY_BYTES, access=mmap.ACCESS_READ)
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            finally:
                os.close(descriptor)
            warnings = list(compiled.warnings)
            warnings.append("Preview only: no frames, events or alerts are saved." if request.preview_only else
                "Recording stops after 240 frames, 256 MiB per session, or 2 GiB total; earlier evidence is retained.")
            status = LiveStatus(session_id=identifier, project_id=project_id, shared_memory_path=str(path),
                preview_only=request.preview_only, source_kind=request.source_kind, source_label=request.source_label,
                sample_fps=fps, warnings=warnings)
            status_path = None if request.preview_only else root / "live" / identifier / "status.json"
            session = Session(status, request.candidate_index, approved, compiled, mapping, status_path)
            try:
                self._save_status(session)
            except BaseException:
                mapping.close()
                path.unlink(missing_ok=True)
                raise
            self.sessions[identifier] = session
            if self.worker is None:
                self.worker = threading.Thread(target=self._sweeper, name="live-session-cleanup", daemon=True)
                self.worker.start()
            # Ephemeral status history is bounded; recorded status remains on disk.
            for key in list(self.sessions):
                if len(self.sessions) <= 128:
                    break
                old = self.sessions[key]
                if old.status.state != "running" and not old.busy:
                    del self.sessions[key]
            return status.model_copy(deep=True)

    def _session(self, project_id: str, identifier: str) -> Session:
        with self.lock:
            session = self.sessions.get(identifier)
        if session is None or session.status.project_id != project_id:
            raise LiveError("Live session not found", 404)
        return session

    def status(self, project_id: str, identifier: str) -> LiveStatus:
        try:
            session = self._session(project_id, identifier)
        except LiveError:
            if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
                raise LiveError("Live session not found", 404) from None
            with self.lock:
                if not self.closed:
                    self._ensure_lease()
            path = self.service.root(project_id) / "live" / identifier / "status.json"
            if not path.is_file():
                raise LiveError("Live session not found", 404) from None
            status = LiveStatus.model_validate_json(path.read_text())
            if status.state in {"running", "stopping"} and self.closed:
                status.state, status.error = "failed", "Capture belongs to a previous or another engine process"
            return status
        with session.lock:
            return session.status.model_copy(deep=True)

    def stop(self, project_id: str, identifier: str) -> LiveStatus:
        try:
            session = self._session(project_id, identifier)
        except LiveError:
            return self.status(project_id, identifier)
        with session.lock:
            if session.status.state == "running":
                self._finish(session, "stopped")
            return session.status.model_copy(deep=True)

    def frame(self, project_id: str, identifier: str, request: FrameRequest) -> FrameResponse:
        try:
            session = self._session(project_id, identifier)
        except LiveError:
            previous = self.status(project_id, identifier)
            raise LiveError(previous.error or "Live session has ended", 410) from None
        with session.lock:
            status = session.status
            if status.state != "running":
                raise LiveError(status.error or "Live session is stopped", 410)
            if session.busy:
                raise LiveError("One frame is already in flight; wait before writing shared memory", 409)
            if time.monotonic() - session.created >= status.max_duration_s:
                self._finish(session, "limit_reached", "Maximum live-session duration reached")
                raise LiveError(status.error or "Session limit reached", 410)
            if ((status.last_sequence is not None and request.sequence <= status.last_sequence)
                    or (status.last_timestamp_s is not None and request.timestamp_s <= status.last_timestamp_s)):
                self._finish(session, "failed", "Frame sequence and source timestamps must strictly increase")
                raise LiveError(status.error or "Invalid frame ordering")
            if status.last_timestamp_s is not None and request.timestamp_s - status.last_timestamp_s + 1e-6 < 1 / status.sample_fps:
                raise LiveError(f"Frame exceeds pipeline sampling rate of {status.sample_fps:g} fps", 409)
            assert session.mapping is not None
            raw = session.mapping[:request.bytes_per_row * request.height]
            image = Image.frombytes("RGBA", (request.width, request.height), raw,
                                    "raw", "BGRA", request.bytes_per_row, 1).convert("RGB")
            status.last_sequence, status.last_timestamp_s = request.sequence, request.timestamp_s
            session.activity, session.busy = time.monotonic(), True
        started = time.perf_counter()
        try:
            with self.service.repository.lock:
                approval.recheck(self.service, project_id, session.index, status.preview_only, session.approved)
            with session.lock:
                if status.state != "running":
                    raise LiveError("Live capture stopped before inference; frame discarded", 410)
            result = execute_image(session.compiled, image, f"live://{identifier}/{request.sequence}",
                                   request.timestamp_s, session.temporal)
            with self.service.repository.lock:
                project = approval.recheck(self.service, project_id, session.index, status.preview_only, session.approved)
                with session.lock:
                    if status.state != "running":
                        raise LiveError("Live capture stopped during inference; result discarded", 410)
                    if not status.preview_only:
                        assert session.approved.deployment_id is not None
                        size = persistence.persist(self.service, project, status, session.approved.deployment_id,
                                                   image, result, request.sequence)
                        status.retained_frames += 1
                        status.retained_bytes += size
                    status.processed_frames += 1
                    if not status.preview_only and status.retained_frames >= status.max_retained_frames:
                        self._finish(session, "limit_reached", "Retained-frame limit reached; earlier evidence remains available")
                    else:
                        self._save_status(session)
                    return FrameResponse(session_id=identifier, state=status.state, result=result,
                        processing_ms=(time.perf_counter() - started) * 1000, processed_frames=status.processed_frames,
                        retained_frames=status.retained_frames, retained_bytes=status.retained_bytes)
        except Exception as error:
            with session.lock:
                if status.state == "running":
                    terminal: SessionState = "limit_reached" if isinstance(error, LiveError) and error.status_code == 413 else "failed"
                    self._finish(session, terminal, str(error))
            if isinstance(error, LiveError):
                raise
            raise LiveError(f"Live inference failed: {error}") from error
        finally:
            with session.lock:
                session.busy = False

    def _sweeper(self) -> None:
        while not self.wake.wait(5):
            self._expire_sessions()

    def _expire_sessions(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            with session.lock:
                now = time.monotonic()
                if session.status.state == "running" and now - session.activity >= session.status.idle_timeout_s:
                    self._finish(session, "stopped", "Live session expired after five minutes without frames")
                elif session.status.state == "running" and now - session.created >= session.status.max_duration_s:
                    self._finish(session, "limit_reached", "Maximum live-session duration reached")

    def close(self) -> None:
        with self.lock:
            self.closed = True
            sessions = list(self.sessions.values())
        self.wake.set()
        for session in sessions:
            with session.lock:
                if session.status.state == "running":
                    self._finish(session, "stopped", "Engine shut down")
        if self.worker is not None:
            self.worker.join(timeout=2)
        if self.owns_lease:
            self.lease.release()
            self.owns_lease = False
