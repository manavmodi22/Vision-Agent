"""Deterministic, complete-scope evidence execution behind typed MCP tools."""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from engine.datasets import DatasetMetadata
from engine.service import WorkspaceService
from engine.store.models import EventRecord
from engine.zones import read_zone_state
from spec.evidence import (
    EvidenceAnswer,
    EvidenceContext,
    EvidenceInterpretation,
    EvidenceQuery,
    TimeScope,
)


def machine_timezone(requested: str | None = None) -> str:
    """Resolve an IANA zone; never silently substitute a fixed offset or LA."""
    candidate = requested or os.environ.get("TZ")
    if not candidate:
        local = str(Path("/etc/localtime").resolve())
        if "/zoneinfo/" in local:
            candidate = local.split("/zoneinfo/", 1)[1]
        elif Path("/etc/timezone").is_file():
            candidate = Path("/etc/timezone").read_text().strip()
    if not candidate or len(candidate) > 100:
        raise ValueError("Pass an IANA timezone, such as Europe/London, for evidence questions")
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Evidence timezone must be a valid IANA timezone") from error
    return candidate


def resolve_scope(scope: TimeScope, timezone: str, reference: datetime) -> tuple[datetime | None, datetime]:
    if reference.tzinfo is None:
        raise ValueError("Evidence reference time must include a timezone")
    zone = ZoneInfo(timezone)
    reference = reference.astimezone(UTC)
    local_day = reference.astimezone(zone).date()
    midnight = datetime.combine(local_day, time.min, zone)
    if scope.period == "all_time":
        return None, reference
    if scope.period == "today":
        return midnight.astimezone(UTC), reference
    if scope.period == "yesterday":
        return (midnight - timedelta(days=1)).astimezone(UTC), midnight.astimezone(UTC)
    if scope.period in {"last_hours", "last_days"}:
        amount = scope.amount or 1  # TimeScope has already required amount.
        duration = timedelta(hours=amount) if scope.period == "last_hours" else timedelta(days=amount)
        return reference - duration, reference
    if scope.start_date is None or scope.end_date is None:
        raise ValueError("Calendar dates are required")
    if scope.end_date > local_day:
        raise ValueError("Future evidence periods are unavailable")
    start = datetime.combine(scope.start_date, time.min, zone).astimezone(UTC)
    end = datetime.combine(scope.end_date + timedelta(days=1), time.min, zone).astimezone(UTC)
    if start >= reference or end > reference and scope.end_date > local_day:
        raise ValueError("Future evidence periods are unavailable")
    return start, min(end, reference)


@contextmanager
def evidence_connection(service: WorkspaceService) -> Iterator[sqlite3.Connection]:
    """Read-only SQLite snapshot with a deadline; never return a partial count."""
    connection = sqlite3.connect(f"{service.repository.database.as_uri()}?mode=ro", uri=True, timeout=3)
    deadline = monotonic() + 8
    connection.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
    try:
        connection.execute("BEGIN")
        yield connection
    except sqlite3.OperationalError as error:
        raise ValueError("Evidence query could not complete; no partial count was returned") from error
    finally:
        connection.close()


def evidence_context(service: WorkspaceService, project_id: str, timezone: str | None = None) -> EvidenceContext:
    project = service.get_project(project_id)
    zone = machine_timezone(timezone)
    metadata_path = service.root(project_id) / "dataset-metadata.json"
    metadata = DatasetMetadata.model_validate_json(metadata_path.read_text()) if metadata_path.exists() else DatasetMetadata()
    labels = {item.name for item in metadata.classes}
    labels.update(box.label for row in service.annotations(project_id).annotations for box in row.detections)
    zones: set[str] = set()
    for candidate in project.candidates:
        for block in candidate.blocks:
            values = block.params.get("classes")
            if isinstance(values, list):
                labels.update(value for value in values if isinstance(value, str))
    for path in (service.root(project_id) / "zones").glob("*.json"):
        if path.name == "lanes.json" and not read_zone_state(service.root(project_id)).confirmed:
            continue
        document = json.loads(path.read_text())
        values = document.get("zones", []) if isinstance(document, dict) else []
        zones.update(str(item["id"]) for item in values if isinstance(item, dict) and "id" in item)
    with evidence_connection(service) as connection:
        stats = connection.execute(
            "SELECT COUNT(*), MIN(created_at), MAX(created_at), SUM(julianday(created_at) IS NULL) "
            "FROM events WHERE project_id=?", (project_id,),
        ).fetchone()
        if stats[3]:
            raise ValueError("Stored evidence has invalid timestamps; a complete time query is unavailable")
        rows = connection.execute(
            "SELECT DISTINCT json_extract(document,'$.label') FROM events WHERE project_id=? "
            "AND json_extract(document,'$.label') IS NOT NULL LIMIT 201", (project_id,),
        )
        labels.update(str(row[0]) for row in rows if row[0] is not None)
        rows = connection.execute(
            "SELECT DISTINCT CAST(COALESCE(json_extract(document,'$.payload.zone'), "
            "json_extract(document,'$.payload.event.zone')) AS TEXT) "
            "FROM events WHERE project_id=? AND COALESCE(json_extract(document,'$.payload.zone'), "
            "json_extract(document,'$.payload.event.zone')) IS NOT NULL LIMIT 101", (project_id,),
        )
        zones.update(str(row[0]) for row in rows if row[0] is not None)
        kinds = [str(row[0]) for row in connection.execute(
            "SELECT DISTINCT json_extract(document,'$.payload.kind') FROM events WHERE project_id=?", (project_id,),
        ) if row[0] is not None]
    if len(labels) > 200 or len(zones) > 100 or any(len(value) > 200 for value in labels | zones):
        raise ValueError("This project's evidence vocabulary exceeds the semantic query context budget")
    return EvidenceContext(project_id=project_id, timezone=zone, reference_time=datetime.now(UTC),
                           labels=sorted(labels), zones=sorted(zones), kinds=sorted(kinds),
                           total_records=stats[0], earliest_record=stats[1], latest_record=stats[2])


def validate_query(query: EvidenceQuery, context: EvidenceContext) -> None:
    if not set(query.labels) <= set(context.labels):
        raise ValueError("The requested label is not in this project's saved or recorded labels; ask for clarification")
    if not set(query.zones) <= set(context.zones):
        raise ValueError("The requested zone is not in this project's saved or recorded zones; ask for clarification")
    resolve_scope(query.time, context.timezone, context.reference_time)


def execute_evidence_query(
    service: WorkspaceService, project_id: str, query: EvidenceQuery,
    timezone: str, reference_time: datetime,
) -> EvidenceAnswer:
    context = evidence_context(service, project_id, timezone)
    now = datetime.now(UTC)
    if reference_time.tzinfo is None or reference_time > now or reference_time < now - timedelta(minutes=5):
        raise ValueError("Evidence reference time must be an aware timestamp from this query session")
    context.reference_time = reference_time
    validate_query(query, context)
    start, end = resolve_scope(query.time, timezone, reference_time)
    clauses = ["project_id=?", "julianday(created_at) < julianday(?)",
               "json_extract(document,'$.payload.kind')=?", "json_extract(document,'$.confidence')>=?"]
    parameters: list[str | float] = [project_id, end.isoformat(), query.kind, query.min_confidence]
    if start is not None:
        clauses.append("julianday(created_at) >= julianday(?)")
        parameters.append(start.isoformat())
    if query.labels:
        clauses.append(f"json_extract(document,'$.label') IN ({','.join('?' for _ in query.labels)})")
        parameters.extend(query.labels)
    if query.text_contains is not None:
        clauses.append("instr(lower(json_extract(document,'$.payload.text')), lower(?)) > 0")
        parameters.append(query.text_contains)
    zone_column = "CAST(COALESCE(json_extract(document,'$.payload.zone'), json_extract(document,'$.payload.event.zone')) AS TEXT)"
    with evidence_connection(service) as connection:
        if query.zones:
            unknown = connection.execute("SELECT COUNT(*) FROM events WHERE " + " AND ".join(clauses)
                                         + f" AND ({zone_column} IS NULL OR {zone_column}='')", parameters).fetchone()[0]
            if unknown:
                question = (f"{unknown:,} otherwise matching observations have no recorded zone. "
                            "A complete zone-filtered count is unavailable. Should I count across all zones instead?")
                return EvidenceAnswer(answer=question, questions=[question])
            clauses.append(f"{zone_column} IN ({','.join('?' for _ in query.zones)})")
            parameters.extend(query.zones)
        where = " AND ".join(clauses)
        counts = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(json_extract(document,'$.payload.synthetic')=1),0), "
            "COALESCE(SUM(json_extract(document,'$.payload.synthetic') IS NULL),0) FROM events WHERE " + where,
            parameters,
        ).fetchone()
        rows = connection.execute(
            "SELECT document FROM events WHERE " + where + " ORDER BY julianday(created_at) DESC, id LIMIT 12",
            parameters,
        ).fetchall()
    evidence = [EventRecord.model_validate_json(row[0]).model_dump(mode="json") for row in rows]
    description = ", ".join(query.labels) or f"all {query.kind} labels"
    if query.zones:
        description += " in zones " + ", ".join(query.zones)
    answer = (f"Found {counts[0]:,} recorded {query.kind} observations for {description}. "
              f"Counted the complete requested period ({timezone}); showing {len(evidence)} matching records. "
              "These are per-frame observations, not unique physical objects; repeated frames or runs may count the same object again. "
              "Dates refer to when records were saved, not camera capture times.")
    if counts[1]:
        answer += f" {counts[1]:,} matching observations are marked synthetic."
    if counts[2]:
        answer += f" Provenance is unspecified for {counts[2]:,} matching observations."
    return EvidenceAnswer(answer=answer, evidence=evidence, interpretation=EvidenceInterpretation(
        query=query, timezone=timezone, start_utc=start, end_utc=end, reference_time=reference_time,
        matched_observations=counts[0], synthetic_observations=counts[1],
        unknown_provenance_observations=counts[2], evidence_returned=len(evidence),
    ))
