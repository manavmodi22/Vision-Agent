import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.evidence_planner import ask_evidence, validate_decision
from agent.machine import AgentError, AgentState, Phase
from agent.mcp_client import connect_tools
from agent.planner import PlannerError
from engine.evidence_query import (
    evidence_context,
    execute_evidence_query,
    machine_timezone,
    resolve_scope,
)
from engine.service import WorkspaceService
from engine.store.models import EventRecord
from engine.zones import save_zone_state
from spec.evidence import EvidenceContext, EvidenceDecision, EvidenceQuery, TimeScope
from spec.models import Zone


def add_event(service: WorkspaceService, project_id: str, identifier: str, *, label: str = "damaged pallet",
              zone: str = "4", created_at: str | None = None, confidence: float = 0.9,
              kind: str = "detection", synthetic: bool = True, text: str = "") -> None:
    service.repository.add_event(project_id, EventRecord(
        id=identifier, created_at=created_at or (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        label=label, confidence=confidence, image_path=f"/synthetic/{identifier}.png",
        crop_path=f"/synthetic/crops/{identifier}.jpg", counts={"4": 99},
        payload={"kind": kind, "zone": zone, "synthetic": synthetic, "text": text},
    ))


def query(**changes: object) -> EvidenceQuery:
    return EvidenceQuery.model_validate({"operation": "count", "labels": ["damaged pallet"],
                                        "zones": ["4"], "kind": "detection", "time": {"period": "all_time"}, **changes})


def test_complete_scope_over_1000_excludes_other_project_and_retains_matching_ids(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Complete scope", "custom")
    other = service.create_project("Other", "custom")
    # Bulk insertion deliberately exceeds both former API and repository defaults.
    with service.repository.connection() as connection:
        for i in range(1205):
            event = EventRecord(id=f"match-{i:04}", created_at="2026-01-01T12:00:00+00:00", label="damaged pallet",
                                image_path=f"/synthetic/{i}.png", crop_path=f"/synthetic/{i}.jpg", confidence=0.9,
                                counts={"4": 999}, payload={"kind": "detection", "zone": "4", "synthetic": True})
            connection.execute("INSERT INTO events VALUES (?,?,?,?)", (event.id, project.id, event.created_at, event.model_dump_json()))
    add_event(service, other.id, "other-project")
    add_event(service, project.id, "wrong-zone", zone="5")
    add_event(service, project.id, "wrong-label", label="pallet")
    add_event(service, project.id, "rule-event", label="damaged pallet", kind="rule")
    result = execute_evidence_query(service, project.id, query(), "UTC", datetime.now(UTC))
    assert result.interpretation is not None
    assert result.interpretation.matched_observations == 1205  # Not 1205*999 repeated counts.
    assert result.interpretation.synthetic_observations == 1205
    assert len(result.evidence) == 12 and all(str(item["id"]).startswith("match-") for item in result.evidence)
    assert all(str(item["crop_path"]).endswith(".jpg") for item in result.evidence)
    assert "not unique physical objects" in result.answer and "synthetic" in result.answer


def test_labels_zones_and_literal_text_are_parameterized(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Literal values", "custom")
    attack = "x' OR 1=1 --"
    add_event(service, project.id, "literal", label=attack, zone=attack)
    add_event(service, project.id, "other")
    result = execute_evidence_query(service, project.id, query(labels=[attack], zones=[attack]), "UTC", datetime.now(UTC))
    assert result.interpretation and result.interpretation.matched_observations == 1
    assert result.evidence[0]["id"] == "literal"
    add_event(service, project.id, "text", label="read text", kind="text", text="SKU_001%")
    result = execute_evidence_query(service, project.id, query(labels=["read text"], kind="text", text_contains="_001%"), "UTC", datetime.now(UTC))
    assert result.interpretation and result.interpretation.matched_observations == 1


def test_rule_nested_zone_is_counted_and_returned(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Rule zone", "custom")
    service.repository.add_event(project.id, EventRecord(id="nested-rule", label="pipeline event", confidence=1,
        image_path="/synthetic/frame.png", created_at="2026-01-01T12:00:00Z",
        payload={"kind": "rule", "event": {"type": "count_rule", "zone": "dock 4"}, "synthetic": True}))
    result = execute_evidence_query(service, project.id, query(kind="rule", labels=["pipeline event"], zones=["dock 4"]),
                                    "UTC", datetime.now(UTC))
    assert result.interpretation and result.interpretation.matched_observations == 1
    assert result.evidence[0]["id"] == "nested-rule"


def test_missing_zone_metadata_does_not_become_a_false_zero_count(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("OCR location unavailable", "custom")
    save_zone_state(service.root(project.id), [Zone(id="A", polygon=[(0, 0), (1, 0), (1, 1), (0, 1)])])
    service.repository.add_event(project.id, EventRecord(id="text-without-zone", label="read text", confidence=1,
        image_path="/synthetic/frame.png", created_at="2026-01-01T12:00:00Z",
        payload={"kind": "text", "text": "SKU-001", "synthetic": True}))
    result = execute_evidence_query(service, project.id, query(kind="text", labels=["read text"], zones=["A"]),
                                    "UTC", datetime.now(UTC))
    assert result.interpretation is None and result.questions and "no recorded zone" in result.answer
    assert result.evidence == []


def test_evidence_context_excludes_unconfirmed_saved_regions(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Unknown geometry", "custom")
    path = service.root(project.id) / "zones/lanes.json"
    path.write_text(json.dumps({"zones": [{"id": "A", "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}]}))
    assert evidence_context(service, project.id, "UTC").zones == []


def test_dst_calendar_dates_and_rolling_duration_are_distinct() -> None:
    reference = datetime(2026, 3, 9, 7, tzinfo=UTC)
    start, end = resolve_scope(TimeScope(period="yesterday"), "America/Los_Angeles", reference)
    assert start == datetime(2026, 3, 8, 8, tzinfo=UTC)
    assert end == reference and (end - start).total_seconds() == 23 * 3600
    rolling, _ = resolve_scope(TimeScope(period="last_days", amount=1), "America/Los_Angeles", reference)
    assert rolling == reference - timedelta(hours=24)
    start, end = resolve_scope(TimeScope(period="between_dates", start_date="2026-03-08", end_date="2026-03-08"),
                               "America/Los_Angeles", reference)
    assert start and (end - start).total_seconds() == 23 * 3600


def test_request_timezone_overrides_machine_and_invalid_zone_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    assert machine_timezone() == "Asia/Kolkata"
    assert machine_timezone("Europe/London") == "Europe/London"
    with pytest.raises(ValueError, match="IANA"):
        machine_timezone("Not/AZone")


def test_calendar_scope_is_half_open_and_compares_offset_timestamps(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Timezone boundaries", "custom")
    add_event(service, project.id, "before", created_at="2025-12-31T18:29:59Z")
    add_event(service, project.id, "start", created_at="2025-12-31T18:30:00Z")
    add_event(service, project.id, "inside", created_at="2026-01-01T19:00:00+05:30")
    add_event(service, project.id, "end", created_at="2026-01-01T18:30:00Z")
    result = execute_evidence_query(service, project.id, query(time={
        "period": "between_dates", "start_date": "2026-01-01", "end_date": "2026-01-01"}),
        "Asia/Kolkata", datetime.now(UTC))
    assert result.interpretation and result.interpretation.matched_observations == 2
    assert {item["id"] for item in result.evidence} == {"start", "inside"}


def test_corrupt_record_time_fails_instead_of_returning_partial_count(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("No partial results", "custom")
    add_event(service, project.id, "valid")
    add_event(service, project.id, "corrupt", created_at="not-a-timestamp")
    with pytest.raises(ValueError, match="invalid timestamps"):
        execute_evidence_query(service, project.id, query(), "UTC", datetime.now(UTC))


def test_query_context_does_not_create_or_edit_project_metadata(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Read only", "custom")
    add_event(service, project.id, "custom", label="leaking drum", zone="loading east")
    before = {str(path): path.read_bytes() for path in service.root(project.id).rglob("*") if path.is_file()}
    context = evidence_context(service, project.id, "UTC")
    assert "leaking drum" in context.labels and "loading east" in context.zones
    after = {str(path): path.read_bytes() for path in service.root(project.id).rglob("*") if path.is_file()}
    assert before == after


@pytest.mark.parametrize("period,changes", [
    ("today", {"amount": 4}), ("last_days", {}),
    ("between_dates", {"start_date": "2026-02-02", "end_date": "2026-01-01"}),
])
def test_inconsistent_time_schema_rejected(period: str, changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TimeScope.model_validate({"period": period, **changes})


def test_unknown_label_unique_counts_and_unsupported_aggregate_are_not_executed() -> None:
    context = EvidenceContext(project_id="p", timezone="UTC", reference_time=datetime.now(UTC),
                              labels=["damaged pallet"], zones=["4"], kinds=["detection"], total_records=0,
                              earliest_record=None, latest_record=None)
    for question in ["How many unique damaged pallets ever?", "Average damaged pallets of all time?",
                     "How many damaged pallets?"]:
        with pytest.raises(ValueError):
            validate_decision(EvidenceDecision(query=query()), question, context)
    with pytest.raises(ValueError, match="Unknown project label"):
        validate_decision(EvidenceDecision(query=query(labels=["invented"])), "Count invented labels of all time", context)
    with pytest.raises(ValueError, match="Today was not requested"):
        validate_decision(EvidenceDecision(query=query(time={"period": "today"})), "How many damaged pallets on dock 4?", context)
    with pytest.raises(ValidationError):
        EvidenceQuery.model_validate({**query().model_dump(), "sql": "DELETE FROM events"})


async def test_query_mcp_can_read_but_not_import_or_deploy(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("MCP evidence", "custom")
    add_event(service, project.id, "match")
    state = AgentState(phase=Phase.QUERY)
    async with connect_tools(str(tmp_path), state) as tools:
        raw = await tools.call("evidence_context", {"project_id": project.id, "timezone": "UTC"})
        context = EvidenceContext.model_validate(raw)
        result = await tools.call("evidence_execute", {"project_id": project.id,
            "query": query().model_dump(mode="json"), "timezone": "UTC", "reference_time": context.reference_time.isoformat()})
        assert result["interpretation"] and len(result["evidence"]) == 1  # type: ignore[arg-type]
        with pytest.raises(AgentError, match="not allowed"):
            await tools.call("media_import", {"project_id": project.id, "paths": []})
    assert service.get_project(project.id).deployment_id is None


async def test_missing_local_model_does_not_use_keyword_fallback(tmp_path: Path) -> None:
    with pytest.raises(PlannerError, match="Choose a planner model"):
        await ask_evidence("How many pallets today?", {"mcp_data_dir": str(tmp_path), "project_id": "test"})


async def test_captured_query_and_dry_replay_do_not_change_build_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import evidence_planner
    from agent.mcp_client import MCPTools
    from agent.state_contracts import TraceQuery
    from engine.evidence_audit import EvidenceAuditStore

    service = WorkspaceService(tmp_path)
    project = service.create_project("Captured query", "custom")
    add_event(service, project.id, "match")
    before = (service.root(project.id) / "project.json").read_bytes()

    async def no_network(url: str, model: str) -> None:
        pass

    async def typed_stub(question: str, context: EvidenceContext, url: str, model: str, tools: MCPTools) -> EvidenceDecision:
        call = await tools.capture_start("explicit-test-stub", {"question": question})
        decision = EvidenceDecision(query=query())
        await tools.capture_finish(call.id, {"stub_decision": decision.model_dump(mode="json")})
        return decision

    monkeypatch.setattr(evidence_planner, "check_model", no_network)
    monkeypatch.setattr(evidence_planner, "_interpret", typed_stub)
    result = await ask_evidence("Count damaged pallets of all time", {"project_id": project.id,
        "mcp_data_dir": str(tmp_path), "planner_model": "explicit-test-stub"}, timezone="UTC")
    assert result.query_id is not None
    audit = EvidenceAuditStore(service)
    record = audit.get(project.id, result.query_id)
    assert record.operation.status == "completed"
    assert record.operation.state.budget.tool_calls == 2 and record.operation.state.budget.model_calls == 1
    spans = audit.traces.query(project.id, TraceQuery(operation_id=result.query_id))
    assert len(spans) == 4 and {item.kind for item in spans} == {"tool", "llm", "run"}
    replay = audit.replay(project.id, result.query_id)
    assert replay.reproduced and replay.dry_run and not replay.effects_executed and replay.answer == result
    assert (service.root(project.id) / "project.json").read_bytes() == before
    assert not (service.root(project.id) / "agent-state.json").exists()
    assert len(service.events(project.id)) == 1


def test_expired_evidence_operation_is_interrupted_without_fabricated_answer(tmp_path: Path) -> None:
    from engine.evidence_audit import EvidenceAuditStore

    service = WorkspaceService(tmp_path)
    project = service.create_project("Interrupted query", "custom")
    audit = EvidenceAuditStore(service)
    record = audit.begin(project.id, "Count all observations of all time")
    audit.start_call(project.id, record.operation.id, "llm", "test-model", {})
    record = audit.get(project.id, record.operation.id)
    record.operation.deadline = 0
    audit.save(record)
    loaded = audit.get(project.id, record.operation.id)
    assert loaded.operation.status == "interrupted" and loaded.operation.calls[0].status == "interrupted"
    replay = audit.replay(project.id, record.operation.id)
    assert not replay.reproduced and replay.answer is None
    assert not (service.root(project.id) / "agent-state.json").exists()


def test_authored_evidence_regression_cases(tmp_path: Path) -> None:
    """Golden typed interpretations, not a benchmark of model-generated semantics."""
    service = WorkspaceService(tmp_path)
    project = service.create_project("Golden query cases", "custom")
    for identifier, label, zone, day, confidence, kind, text in [
        ("a", "damaged pallet", "4", 1, .9, "detection", ""),
        ("b", "damaged pallet", "4", 1, .6, "detection", ""),
        ("c", "damaged pallet", "5", 2, .8, "detection", ""),
        ("d", "pallet", "4", 2, .9, "detection", ""),
        ("e", "forklift", "4", 3, .95, "detection", ""),
        ("f", "leaking drum", "loading east", 4, .8, "detection", ""),
        ("g", "read text", "4", 1, 1.0, "text", "SKU-001"),
        ("h", "pipeline event", "4", 1, 1.0, "rule", ""),
    ]:
        add_event(service, project.id, identifier, label=label, zone=zone, confidence=confidence, kind=kind, text=text,
                  created_at=f"2026-01-{day:02}T12:00:00+00:00")
    context = evidence_context(service, project.id, "UTC")
    cases = json.loads((Path(__file__).parents[1] / "evals" / "evidence_queries.json").read_text())
    assert len(cases) >= 24
    for case in cases:
        decision = EvidenceDecision.model_validate(case["decision"])
        validate_decision(decision, case["question"], context)
        if decision.query:
            result = execute_evidence_query(service, project.id, decision.query, "UTC", datetime.now(UTC))
            assert result.interpretation and result.interpretation.matched_observations == case["expected_count"], case["id"]
        else:
            assert case["expected_count"] is None
