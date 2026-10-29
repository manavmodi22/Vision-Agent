"""Evidence creation and deliberately bounded queries over recorded observations."""
from __future__ import annotations

import csv
import io
import uuid

from PIL import Image

from engine.store.models import Deployment, EventRecord, Project, ReviewRecord
from engine.store.repository import Repository
from spec.models import RunResult


def persist_run(repository: Repository, project: Project, result: RunResult,
                deployment: Deployment | None = None) -> list[EventRecord]:
    root = repository.project_root(project.id)
    crop_dir = root / "crops"
    crop_dir.mkdir(exist_ok=True)
    run_id = uuid.uuid4().hex
    rule_events: list[EventRecord] = []
    approval = {"approval_scope": deployment.approval_scope if deployment else "unknown",
                "evaluation_protocol_id": deployment.protocol_id if deployment else None,
                "evaluation_protocol_hash": deployment.protocol_hash if deployment else None,
                "temporal_event_quality_measured": False}
    for frame in result.frames:
        image_path = (root / frame.image_path).resolve()
        for detection in frame.detections:
            identifier = uuid.uuid4().hex
            crop_path = crop_dir / f"{identifier}.jpg"
            with Image.open(image_path) as image:
                x1, y1, x2, y2 = detection.box
                bounds = (int(x1 * image.width), int(y1 * image.height),
                          max(int(x2 * image.width), int(x1 * image.width) + 1),
                          max(int(y2 * image.height), int(y1 * image.height) + 1))
                image.crop(bounds).convert("RGB").save(crop_path, quality=90)
            repository.add_event(project.id, EventRecord(
                id=identifier, image_path=str(image_path), crop_path=str(crop_path),
                label=detection.label, confidence=detection.confidence,
                counts=frame.counts, payload={**approval, "run_id": run_id, "synthetic": project.synthetic,
                    "zone": detection.zone, "box": list(detection.box), "kind": "detection"},
            ))
            if detection.confidence < 0.55:
                repository.add_review(project.id, ReviewRecord(
                    id=uuid.uuid4().hex, image_path=str(image_path),
                    reason=f"Low confidence {detection.label}: {detection.confidence:.2f}",
                ))
        for index, event in enumerate(frame.events):
            record = EventRecord(
                id=uuid.uuid4().hex, image_path=str(image_path), label="pipeline event",
                confidence=1, counts=frame.counts,
                payload={**approval, "run_id": run_id, "synthetic": project.synthetic,
                         "kind": "rule", "event": event, "event_index": index},
            )
            repository.add_event(project.id, record)
            rule_events.append(record)
        for value in frame.texts:
            repository.add_event(project.id, EventRecord(
                id=uuid.uuid4().hex, image_path=str(image_path), label="read text",
                confidence=1, counts=frame.counts,
                payload={**approval, "run_id": run_id, "synthetic": project.synthetic,
                         "kind": "text", "text": value},
            ))
        if not frame.detections and not frame.texts:
            repository.add_review(project.id, ReviewRecord(
                id=uuid.uuid4().hex, image_path=str(image_path),
                reason="No detections or readable text; check for missed objects",
            ))
    return rule_events


def events_csv(events: list[EventRecord]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "label", "confidence", "image_path", "crop_path",
                     "synthetic", "counts", "approval_scope", "evaluation_protocol_id"])
    for event in events:
        # Prevent spreadsheet formula interpretation in exported text.
        label = "'" + event.label if event.label[:1] in {"=", "+", "-", "@"} else event.label
        writer.writerow([event.id, event.created_at, label, event.confidence,
                         event.image_path, event.crop_path, event.payload.get("synthetic"),
                         str(event.counts), event.payload.get("approval_scope", "unknown"),
                         event.payload.get("evaluation_protocol_id")])
    return output.getvalue()
