# ADR 003: durable agent operations, local tracing and effect-free replay

Status: accepted for implementation. Owner: agent/backend engineer.

## Contracts and ownership

`agent.state_contracts` defines `ProjectAgentState`, `AgentOperation`,
`CapturedCall`, `TraceQuery`, `TraceRecord` and `ReplayReport`. Public data is typed,
JSON serializable and rejects extra fields. `PlanResult.operation_id` is a random
operation token returned by the actual durable planner run.

`engine.agent_state.AgentStateStore(service: WorkspaceService)` is an explicit
application composition boundary. It may import the pure agent state machine;
compiler/runtime/model modules continue to have no agent or planner dependency.
It owns atomic project `agent-state.json` and `agent-runs/<operation_id>.json`.
The existing repository FileLock serializes these files across API/MCP processes.

Public integration methods:

* `get(project_id) -> ProjectAgentState`: reconcile real project evidence and
  interrupted owners, preserving prior budgets, brief and clarifier count.
* `runs(project_id) -> list[AgentOperation]` and `operation(project_id, run_id)`.
* `begin(project_id, brief, source_path, detector_model) -> AgentOperation`:
  claim one active operation; conflicting requests fail rather than overwrite.
* `commit_plan(project_id, operation_id, result, user_prompt) -> Project`: verify
  operation token, captured result and input fingerprint, then atomically save
  candidates/messages/clarification budget and finish the operation. The API must
  not run its old save/message block for the same agent result.
* `reconcile(project_id, action) -> ProjectAgentState`: derive phase/evaluation/
  approval only from saved service records and current hashes, never LLM claims.
* `replay(project_id, operation_id) -> ReplayReport`: read captured decisions and
  tool results, reconstruct typed pattern compilation without invoking a model,
  engine runtime, tool, alert, training or deployment.

`engine.api.agent_routes.build_router(service)` exposes read-only state, run and
trace queries plus explicit POST dry-run replay. Root mounts this router.

## Agent/MCP flow

The harness reads/writes durable state only through MCP management tools. An
operation starts before inference. Every actual planner request (including
retries) captures its request/response and timings. Every vision tool invocation
is dispatched through a durable wrapper that checks phase and budget before the
tool runs, stores a pending call before execution, then records success/failure.
Compilation is complete only after the captured compiler success and nonempty
preview for each candidate; model prose cannot satisfy this gate.

The planner can stage a proposal but cannot commit it or approve deployment via
MCP. The original user-facing API invocation commits the operation token returned
by `plan()`. The store rejects a token for a different project, duplicate or
changed results, another operation, or changed media/zones/labels/candidates.

## Crash and concurrency behavior

An operation records its owning MCP process ID and a bounded deadline. A new
read/begin detects a dead owner or expired deadline and marks pending work
interrupted. Awaiting-commit proposals have a short bounded commit window; they
cannot be auto-deployed or automatically committed after restart. An interrupted
operation retains its consumed budget and captured calls. A subsequent explicit
Build action creates a new operation with a new budget; it does not rewrite the
old run. Source edits invalidate pending proposals and stale evidence.

## Telemetry and replay

`engine.agent_traces` uses the OpenTelemetry SDK with a local JSONL SpanExporter.
Each span carries project/operation/call correlation IDs and local captured
request/result JSON. No image bytes, API credentials or HTTP headers are logged.
The application data directory is the local owner of these traces. An optional
OTLP HTTP exporter uses an explicitly configured loopback OTLP endpoint so a
local Phoenix/Langfuse/collector can consume the same spans.

Replay is a diagnostic reconstruction, not a new run. It reports original
failure states, verifies recorded tool input/output consistency, and states
whether the compiled candidate documents match. It never manufactures current
evaluation evidence or approval. Changed current files do not cause replay to
read or execute those files; it uses the captured results exclusively.

## Required verification

Tests cover interprocess conflicting starts, stale-source commit rejection,
token/result tampering, crash reconciliation, no fabricated approval, preserved
questions/budgets, real MCP state roundtrips, one trace per request/tool attempt,
local JSONL export and explicit effect-free replay. Existing 24-case authored
pattern regression remains separate from live model-quality probes.
