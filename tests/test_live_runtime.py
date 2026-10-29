"""Native mmap handshake, evidence gates, bounded storage and stop races."""
from __future__ import annotations

import mmap
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from agent.templates import build_template
from engine.live import LiveManager
from engine.live.contracts import CAPACITY_BYTES, FrameRequest, LiveError, LiveStatus, StartRequest
from engine.service import WorkspaceService


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[WorkspaceService, str]:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Isolated live fixture", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1"), "Count test rectangles")
    return service, project.id


@pytest.fixture()
def manager(workspace: tuple[WorkspaceService, str]) -> Iterator[LiveManager]:
    live = LiveManager(workspace[0])
    yield live
    live.close()


def start(live: LiveManager, project_id: str, preview: bool = True) -> LiveStatus:
    return live.start(project_id, StartRequest(source_kind="recorded_video", source_label="isolated test", preview_only=preview))


def write_frame(service: WorkspaceService, project_id: str, status: LiveStatus, sequence: int,
                timestamp: float, padding: int = 0) -> FrameRequest:
    with Image.open(service.get_project(project_id).media[1]) as image:
        rgba = image.convert("RGBA")
    packed = rgba.tobytes("raw", "BGRA")
    stride = rgba.width * 4 + padding
    content = b"".join(packed[y * rgba.width * 4:(y + 1) * rgba.width * 4] + b"\xff" * padding for y in range(rgba.height))
    with Path(status.shared_memory_path).open("r+b") as file:
        with mmap.mmap(file.fileno(), status.capacity_bytes) as mapping:
            mapping[:len(content)] = content
    return FrameRequest(sequence=sequence, width=rgba.width, height=rgba.height,
                        bytes_per_row=stride, timestamp_s=timestamp)


def approve(service: WorkspaceService, project_id: str) -> None:
    service.evaluate(project_id)
    service.deploy(project_id, 0, True)


def test_preview_stride_pixels_private_ingress_and_no_persistence(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    status = start(manager, project_id)
    path = Path(status.shared_memory_path)
    assert path.stat().st_mode & 0o777 == 0o600 and path.stat().st_size == CAPACITY_BYTES
    request = write_frame(service, project_id, status, 1, 0, padding=16)
    response = manager.frame(project_id, status.session_id, request)
    assert response.result.counts == {"A": 1, "B": 3, "C": 1, "D": 3}
    assert response.result.image_path.startswith("live://")
    assert response.processed_frames == 1 and response.retained_frames == 0
    assert not service.events(project_id) and not (service.root(project_id) / "live").exists()
    assert manager.stop(project_id, status.session_id).state == "stopped" and not path.exists()
    with pytest.raises(LiveError) as error:
        manager.frame(project_id, status.session_id, request)
    assert error.value.status_code == 410


def test_recording_requires_current_explicit_approval(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    with pytest.raises(LiveError, match="Approve deployment"):
        start(manager, project_id, False)
    approve(service, project_id)
    status = start(manager, project_id, False)
    request = write_frame(service, project_id, status, 1, 0)
    labels = service.annotations(project_id)
    labels.annotations[0].reviewed = False
    service.save_annotations(project_id, labels)
    with pytest.raises(LiveError, match="Approve deployment"):
        manager.frame(project_id, status.session_id, request)
    assert manager.status(project_id, status.session_id).state == "failed"
    assert not service.events(project_id)


def test_recording_persists_and_stops_at_visible_cap_without_deleting(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    manager.sessions[status.session_id].status.max_retained_frames = 2
    paths = []
    for index in range(2):
        request = write_frame(service, project_id, status, index + 1, index * .5)
        response = manager.frame(project_id, status.session_id, request)
        paths.append(Path(response.result.image_path))
    assert response.state == "limit_reached" and response.retained_frames == 2
    assert all(path.is_file() for path in paths) and service.events(project_id)
    assert not Path(status.shared_memory_path).exists()
    assert manager.status(project_id, status.session_id).retained_bytes > 0
    manager.close()
    resumed = LiveManager(service)
    try:
        assert resumed.status(project_id, status.session_id).state == "limit_reached"
    finally:
        resumed.close()


@pytest.mark.parametrize("change", [{"width": 0}, {"width": 8193}, {"bytes_per_row": 3},
                                     {"bytes_per_row": 400, "width": 101},
                                     {"height": 8192, "bytes_per_row": 32768},
                                     {"timestamp_s": float("nan")}, {"sequence": True}])
def test_invalid_metadata_rejected(change: dict[str, object]) -> None:
    payload = {"sequence": 1, "width": 100, "height": 100, "bytes_per_row": 400, "timestamp_s": 0, **change}
    with pytest.raises(ValidationError):
        FrameRequest.model_validate(payload)


def test_ordering_fails_closed_but_sampling_conflict_can_retry(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    status = start(manager, project_id)
    request = write_frame(service, project_id, status, 1, 0)
    manager.frame(project_id, status.session_id, request)
    with pytest.raises(LiveError) as conflict:
        manager.frame(project_id, status.session_id, request.model_copy(update={"sequence": 2, "timestamp_s": .1}))
    assert conflict.value.status_code == 409 and manager.status(project_id, status.session_id).state == "running"
    manager.frame(project_id, status.session_id, request.model_copy(update={"sequence": 2, "timestamp_s": .5}))
    with pytest.raises(LiveError, match="strictly increase"):
        manager.frame(project_id, status.session_id, request.model_copy(update={"sequence": 3, "timestamp_s": .5}))
    assert not Path(status.shared_memory_path).exists()


def test_temporal_rules_share_state_only_within_a_session(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    project = service.get_project(project_id)
    for block in project.candidates[0].blocks:
        if block.type == "rule":
            block.params.update({"hold_s": .5, "when": "count >= 1"})
    service.repository.save(project)
    first, second = start(manager, project_id), start(manager, project_id)
    for session in (first, second):
        request = write_frame(service, project_id, session, 1, 0)
        assert manager.frame(project_id, session.session_id, request).result.events == []
    request = write_frame(service, project_id, first, 2, .5)
    assert manager.frame(project_id, first.session_id, request).result.events
    assert manager.sessions[first.session_id].temporal is not manager.sessions[second.session_id].temporal


def test_stop_during_inference_discards_results_and_shared_bytes_are_copied(
    workspace: tuple[WorkspaceService, str], manager: LiveManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.live.manager as module
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    request = write_frame(service, project_id, status, 1, 0)
    entered, release = threading.Event(), threading.Event()
    execute = module.execute_image
    observed = []
    def slow(*args: object, **kwargs: object) -> object:
        image = args[1]
        assert isinstance(image, Image.Image)
        observed.append(image.getpixel((200, 100)))
        entered.set()
        assert release.wait(10)
        observed.append(image.getpixel((200, 100)))
        return execute(*args, **kwargs)
    monkeypatch.setattr(module, "execute_image", slow)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(manager.frame, project_id, status.session_id, request)
        assert entered.wait(10)
        with pytest.raises(LiveError, match="already in flight"):
            manager.frame(project_id, status.session_id, request.model_copy(update={"sequence": 2, "timestamp_s": .5}))
        # Mutation after the owned copy cannot alter the in-flight pixels.
        with Path(status.shared_memory_path).open("r+b") as file:
            with mmap.mmap(file.fileno(), CAPACITY_BYTES) as mapping:
                mapping[:request.bytes_per_row * request.height] = bytes(request.bytes_per_row * request.height)
        assert manager.stop(project_id, status.session_id).state == "stopped"
        release.set()
        with pytest.raises(LiveError, match="discarded"):
            future.result(10)
    assert observed[0] == observed[1] and not service.events(project_id)
    assert not list((service.root(project_id) / "live" / status.session_id).glob("frame-*.png"))


def test_changes_during_inference_revoke_recording(workspace: tuple[WorkspaceService, str], manager: LiveManager, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.live.manager as module
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    execute = module.execute_image
    def changed(*args: object, **kwargs: object) -> object:
        result = execute(*args, **kwargs)
        with service.repository.lock:
            project = service.get_project(project_id)
            service.invalidate(project)
            service.repository.save(project)
        return result
    monkeypatch.setattr(module, "execute_image", changed)
    request = write_frame(service, project_id, status, 1, 0)
    with pytest.raises(LiveError, match="Approve deployment"):
        manager.frame(project_id, status.session_id, request)
    assert not service.events(project_id) and manager.status(project_id, status.session_id).state == "failed"


def test_second_process_manager_cannot_clean_live_ingress(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    first = start(manager, project_id)
    other = LiveManager(service)
    try:
        with pytest.raises(LiveError, match="Another engine"):
            start(other, project_id)
        assert Path(first.shared_memory_path).exists()
    finally:
        other.close()


def test_live_crops_and_low_confidence_review_are_retained_once_per_frame(
    workspace: tuple[WorkspaceService, str], manager: LiveManager, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.live.manager as module
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    execute = module.execute_image
    def uncertain(*args: object, **kwargs: object) -> object:
        result = execute(*args, **kwargs)
        for detection in result.detections:
            detection.confidence = .4
        return result
    monkeypatch.setattr(module, "execute_image", uncertain)
    request = write_frame(service, project_id, status, 1, 0)
    response = manager.frame(project_id, status.session_id, request)
    events = [event for event in service.events(project_id) if event.payload.get("kind") == "detection"]
    assert len(events) == 8 and all(event.crop_path and Path(event.crop_path).is_file() for event in events)
    with Image.open(events[0].crop_path) as crop:
        assert crop.width < request.width and crop.height < request.height
    reviews = service.review(project_id)
    assert len(reviews) == 1 and "Low confidence" in reviews[0].reason
    physical = sum(path.stat().st_size for path in Path(response.result.image_path).parent.glob("frame-*"))
    assert response.retained_bytes >= physical


def test_retention_byte_cap_rejects_before_writing_evidence(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    manager.sessions[status.session_id].status.max_retained_bytes = 1
    request = write_frame(service, project_id, status, 1, 0)
    with pytest.raises(LiveError) as error:
        manager.frame(project_id, status.session_id, request)
    assert error.value.status_code == 413
    assert manager.status(project_id, status.session_id).state == "limit_reached"
    assert not service.events(project_id)
    assert not list((service.root(project_id) / "live" / status.session_id).glob("frame-*"))


def test_database_failure_removes_all_new_frame_and_crop_files(workspace: tuple[WorkspaceService, str], manager: LiveManager, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3
    from contextlib import contextmanager
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    request = write_frame(service, project_id, status, 1, 0)
    @contextmanager
    def broken() -> Iterator[object]:
        raise sqlite3.OperationalError("isolated injected commit failure")
        yield None
    monkeypatch.setattr(service.repository, "connection", broken)
    with pytest.raises(LiveError, match="commit failure"):
        manager.frame(project_id, status.session_id, request)
    assert not list((service.root(project_id) / "live" / status.session_id).glob("frame-*"))


def test_idle_duration_and_session_limits_are_explicit(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    _, project_id = workspace
    first, second = start(manager, project_id), start(manager, project_id)
    with pytest.raises(LiveError, match="two live"):
        start(manager, project_id)
    manager.sessions[first.session_id].activity -= 301
    manager.sessions[second.session_id].created -= 3601
    manager._expire_sessions()
    assert manager.status(project_id, first.session_id).state == "stopped"
    assert manager.status(project_id, second.session_id).state == "limit_reached"
    assert not Path(first.shared_memory_path).exists() and not Path(second.shared_memory_path).exists()


def test_manager_is_lazy_until_a_session_starts(manager: LiveManager) -> None:
    assert manager.worker is None and not manager.owns_lease
    manager.close()
    assert manager.worker is None


def test_restart_recovers_interrupted_recording_and_orphan_buffer(workspace: tuple[WorkspaceService, str], manager: LiveManager) -> None:
    from engine.live.contracts import FrameRequest
    from engine.store.repository import atomic_model
    service, project_id = workspace
    approve(service, project_id)
    status = start(manager, project_id, False)
    manager.close()
    # Simulate durable state left behind by an unclean engine exit.
    status.state = "running"
    path = service.root(project_id) / "live" / status.session_id / "status.json"
    atomic_model(path, status)
    Path(status.shared_memory_path).write_bytes(b"orphaned private buffer")
    recovered = LiveManager(service)
    try:
        result = recovered.status(project_id, status.session_id)
        assert result.state == "failed" and "restarted" in (result.error or "")
        assert not Path(status.shared_memory_path).exists()
        assert LiveStatus.model_validate_json(path.read_text()).state == "failed"
        with pytest.raises(LiveError) as error:
            recovered.frame(project_id, status.session_id, FrameRequest(sequence=1,width=1,height=1,bytes_per_row=4,timestamp_s=0))
        assert error.value.status_code == 410
    finally:
        recovered.close()
