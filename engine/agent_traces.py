"""OpenTelemetry SDK spans exported locally; optional loopback OTLP viewer."""

import json
import os
from collections import deque
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags
from pydantic import JsonValue, TypeAdapter

from agent.state_contracts import AgentOperation, CapturedCall, TraceQuery, TraceRecord

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class LocalJSONLExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = FileLock(path.with_suffix(".lock"), timeout=10)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        records: list[str] = []
        for span in spans:
            context = span.context
            if context is None or span.start_time is None or span.end_time is None:
                return SpanExportResult.FAILURE
            attributes = JSON_OBJECT.validate_python(dict(span.attributes or {}))
            record = TraceRecord(
                trace_id=f"{context.trace_id:032x}", span_id=f"{context.span_id:016x}",
                parent_span_id=f"{span.parent.span_id:016x}" if span.parent else None,
                name=span.name, project_id=str(attributes.get("vision.project_id", "")),
                operation_id=str(attributes.get("vision.operation_id", "")),
                kind=str(attributes.get("vision.kind", "")),
                start_ns=span.start_time, end_ns=span.end_time,
                status=span.status.status_code.name, attributes=attributes,
            )
            records.append(record.model_dump_json() + "\n")
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.writelines(records)
            stream.flush()
            os.fsync(stream.fileno())
        return SpanExportResult.SUCCESS


class AgentTraceStore:
    """Emit retrospective SDK spans using durable attempt start/end timestamps."""

    def __init__(self, data_dir: Path) -> None:
        self.exporter = LocalJSONLExporter(data_dir / "traces" / "spans.jsonl")
        self.processors = [SimpleSpanProcessor(self.exporter)]
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if endpoint:
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("VisionApp's optional OTLP viewer must use an explicitly configured loopback endpoint")
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            target = endpoint.rstrip("/")
            if not target.endswith("/v1/traces"):
                target += "/v1/traces"
            self.processors.append(SimpleSpanProcessor(OTLPSpanExporter(endpoint=target, timeout=1)))
        self.resource = Resource.create({"service.name": "visionapp-agent", "service.version": "0.1.0"})

    def emit(self, operation: AgentOperation, call: CapturedCall | None = None) -> None:
        failed = (call.status if call else operation.status) in {"failed", "interrupted", "invalidated"}
        attributes: dict[str, str | int | bool] = {
            "vision.project_id": operation.project_id, "vision.operation_id": operation.id,
            "vision.kind": call.kind if call else "run", "vision.phase": operation.state.phase.value,
            "vision.status": call.status if call else operation.status,
            "vision.skills": json.dumps([skill.model_dump(mode="json") for skill in operation.skills], sort_keys=True),
        }
        if call:
            attributes.update({"vision.call_id": call.id,
                               "vision.request": json.dumps(call.request, ensure_ascii=False),
                               "vision.result": json.dumps(call.result, ensure_ascii=False),
                               "vision.error": call.error or ""})
        else:
            attributes.update({"vision.tool_calls": operation.state.budget.tool_calls,
                               "vision.model_calls": operation.state.budget.model_calls,
                               "vision.error": operation.error or ""})
        context = SpanContext(trace_id=int(operation.trace_id, 16),
                              span_id=int(call.id[:16] if call else operation.root_span_id, 16),
                              is_remote=False, trace_flags=TraceFlags(TraceFlags.SAMPLED))
        parent = SpanContext(trace_id=int(operation.trace_id, 16), span_id=int(operation.root_span_id, 16),
                             is_remote=False, trace_flags=TraceFlags(TraceFlags.SAMPLED)) if call else None
        span = ReadableSpan(
            name=f"{call.kind}.{call.name}" if call else "agent.run", context=context, parent=parent,
            kind=SpanKind.CLIENT if call and call.kind == "llm" else SpanKind.INTERNAL,
            resource=self.resource, attributes=attributes,
            start_time=call.started_ns if call else int(operation.created_at * 1e9),
            end_time=(call.ended_ns or call.started_ns) if call else int(operation.updated_at * 1e9),
            status=Status(StatusCode.ERROR if failed else StatusCode.OK),
        )
        for processor in self.processors:
            processor.on_end(span)

    def query(self, project_id: str, query: TraceQuery) -> list[TraceRecord]:
        if not self.exporter.path.exists():
            return []
        records: deque[TraceRecord] = deque(maxlen=query.limit)
        with self.exporter.lock, self.exporter.path.open(encoding="utf-8") as stream:
            for line in stream:
                record = TraceRecord.model_validate_json(line)
                if record.project_id != project_id:
                    continue
                if query.operation_id and record.operation_id != query.operation_id:
                    continue
                if query.kind and record.kind != query.kind:
                    continue
                records.append(record)
        return list(reversed(records))
