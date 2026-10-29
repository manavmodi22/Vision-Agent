"""Bounded evidence commits for approved sessions; preview never calls this module."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from PIL import Image
from pydantic import JsonValue

from engine.alerts.service import AlertService
from engine.live.contracts import MAX_RECORDINGS, MAX_TOTAL_BYTES, LiveError, LiveStatus
from engine.service import WorkspaceService
from engine.store.models import Deployment, EventRecord, Project, ReviewRecord
from engine.store.repository import atomic_model
from spec.models import FrameResult


def folders(service: WorkspaceService) -> list[Path]:
    return list(service.repository.projects_dir.glob("*/live/*"))


def storage_bytes(service: WorkspaceService) -> int:
    total = 0
    for folder in folders(service):
        physical = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
        status_path = folder / "status.json"
        logical = LiveStatus.model_validate_json(status_path.read_text()).retained_bytes if status_path.is_file() else 0
        total += max(physical, logical)
    return total


def ensure_capacity(service: WorkspaceService) -> None:
    if len(folders(service)) >= MAX_RECORDINGS:
        raise LiveError(f"Live recording limit of {MAX_RECORDINGS} sessions reached. Archive retained live evidence before recording more.", 409)
    if storage_bytes(service) >= MAX_TOTAL_BYTES:
        raise LiveError("Live evidence storage is full (2 GiB). Archive retained evidence before recording more.", 409)


def persist(service: WorkspaceService, project: Project, status: LiveStatus, deployment_id: str,
            image: Image.Image, frame: FrameResult, sequence: int) -> int:
    """Caller holds workspace and session locks, and has just rechecked approval."""
    if len(frame.detections) + len(frame.events) + len(frame.texts) > 1000:
        raise LiveError("Frame exceeds the 1,000-observation live evidence limit")
    folder = service.root(project.id) / "live" / status.session_id
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    image_path = folder / f"frame-{sequence:09d}.png"
    frame.image_path = str(image_path)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    content = encoded.getvalue()
    crop_bytes: dict[Path, bytes] = {}
    events: list[EventRecord] = []
    deployment = Deployment.model_validate_json((service.root(project.id) / "deployment.json").read_text())
    if deployment.id != deployment_id:
        raise LiveError("Approval changed before evidence persistence", 409)
    common: dict[str, JsonValue] = {"session_id": status.session_id, "source_kind": status.source_kind,
              "source_label": status.source_label, "timestamp_s": frame.timestamp_s,
              "sequence": sequence, "synthetic": project.synthetic, "deployment_id": deployment_id,
              "approval_scope": deployment.approval_scope, "evaluation_protocol_id": deployment.protocol_id,
              "evaluation_protocol_hash": deployment.protocol_hash, "temporal_event_quality_measured": False}
    for index, detection in enumerate(frame.detections):
        x0, y0, x1, y1 = detection.box
        bounds = (int(x0 * image.width), int(y0 * image.height),
                  max(int(x1 * image.width), int(x0 * image.width) + 1),
                  max(int(y1 * image.height), int(y0 * image.height) + 1))
        crop_path = folder / f"frame-{sequence:09d}-crop-{index:04d}.jpg"
        encoded_crop = io.BytesIO()
        image.crop(bounds).save(encoded_crop, format="JPEG", quality=90)
        crop_bytes[crop_path] = encoded_crop.getvalue()
        if status.retained_bytes + len(content) + sum(map(len, crop_bytes.values())) > status.max_retained_bytes:
            raise LiveError("Live crop retention limit reached; capture stopped without deleting prior evidence", 413)
        events.append(EventRecord(id=uuid.uuid4().hex, image_path=str(image_path), crop_path=str(crop_path), label=detection.label,
            confidence=detection.confidence, counts=frame.counts,
            payload={**common, "kind": "detection", "box": list(detection.box), "zone": detection.zone}))
    rules = [EventRecord(id=uuid.uuid4().hex, image_path=str(image_path), label="pipeline event", confidence=1,
        counts=frame.counts, payload={**common, "kind": "rule", "event": event}) for event in frame.events]
    events += rules
    events += [EventRecord(id=uuid.uuid4().hex, image_path=str(image_path), label="read text", confidence=1,
        counts=frame.counts, payload={**common, "kind": "text", "text": value}) for value in frame.texts]
    frame_json = frame.model_dump_json(indent=2)
    documents = [event.model_dump_json() for event in events]
    low_confidence = sorted({item.label for item in frame.detections if item.confidence < .55})
    review = None
    if low_confidence or (not frame.detections and not frame.texts):
        reason = ("Low confidence live detections: " + ", ".join(low_confidence[:5]) if low_confidence else
                  "Live frame has no detections or readable text; check for missed objects")
        review = ReviewRecord(id=uuid.uuid4().hex, image_path=str(image_path), reason=reason)
    logical_bytes = (len(content) + len(frame_json.encode()) + sum(len(item.encode()) for item in documents)
                     + sum(map(len, crop_bytes.values())) + (len(review.model_dump_json().encode()) if review else 0))
    if (status.retained_frames >= status.max_retained_frames
            or status.retained_bytes + logical_bytes > status.max_retained_bytes
            or storage_bytes(service) + logical_bytes + 65536 > status.max_total_bytes):
        raise LiveError("Live evidence retention limit reached; capture stopped without deleting prior evidence", 413)
    result_path = image_path.with_suffix(".json")
    try:
        with image_path.open("xb") as output:
            output.write(content)
        image_path.chmod(0o600)
        for crop_path, data in crop_bytes.items():
            with crop_path.open("xb") as output:
                output.write(data)
            crop_path.chmod(0o600)
        atomic_model(result_path, frame)
        with service.repository.connection() as connection:
            connection.executemany("INSERT INTO events VALUES (?,?,?,?)", [
                (event.id, project.id, event.created_at, document)
                for event, document in zip(events, documents, strict=True)])
            if review is not None:
                connection.execute("INSERT INTO review VALUES (?,?,?,?)",
                    (review.id, project.id, review.image_path, review.model_dump_json()))
    except BaseException:
        image_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)
        for crop_path in crop_bytes:
            crop_path.unlink(missing_ok=True)
        raise
    if deployment.approval_scope == "local_trial":
        warning = "Local trial: evidence is saved locally; external alert delivery is disabled."
        if warning not in status.warnings:
            status.warnings.append(warning)
    else:
        try:
            AlertService(service).enqueue_events(project.id, deployment_id, rules)
        except Exception as error:
            warning = f"Frame evidence was saved, but alert enqueue failed: {error}"[:500]
            if warning not in status.warnings and len(status.warnings) < 32:
                status.warnings.append(warning)
    return logical_bytes
