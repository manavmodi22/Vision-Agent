# Typed evidence questions

## Interface and boundary

`await agent.evidence_planner.ask_evidence(question, settings, timezone=None)`
returns `EvidenceAnswer` with existing `answer` / `evidence` keys plus typed
`interpretation`, `questions`, and `query_id`. Settings supply the saved project
ID, MCP workspace, and loopback planner URL/model. The API owns authentication
and request validation. A missing/unavailable model raises `PlannerError`; there
is no keyword or template fallback.

Shared query contracts live in `spec/evidence.py`. The executor imports no agent
planner. `engine/evidence_audit.py` is an application composition boundary that
reuses the existing agent trace envelope.

The agent reads project labels, zone IDs, record coverage, and the reference
clock through `evidence_context` over stdio MCP. A local model emits only an
`EvidenceDecision`: either a bounded `EvidenceQuery` or up to three clarification
questions. It cannot emit SQL, executable code, a count, evidence IDs, or an
answer. The engine validates exact labels and zones again before executing.
Read-only questions use a separate QUERY tool whitelist and cannot change a
project's build, evaluation, or deployment state.

## Supported meaning

Queries count or show recorded detection, text, or rule observations, filtered by
exact project labels, exact zone IDs, optional literal text, confidence, and an
explicit time scope. Counts are observation rows, never sums of the duplicated
per-frame `counts` dictionary and never unique physical objects. Unsupported
aggregations and absent/ambiguous classes, zones, or periods require clarification.
The model gets actual project vocabulary, not a warehouse keyword list.

Relative dates are resolved deterministically using the request's IANA timezone
or the machine's configured IANA timezone. The reference instant is pinned before
model interpretation. Today/yesterday and calendar date ranges respect local
midnight and daylight-saving transitions. Timestamps mean **record persistence
time**, not original camera capture time. Unspecified time is not silently
defaulted to today or all time.

## Complete and bounded execution

The engine uses fixed parameterized SQLite statements over the complete project
and requested interval. There is no newest-1000 prefilter. Counts and up to twelve
matching evidence rows are read in one database snapshot. A database deadline
fails explicitly instead of returning a partial count. Result evidence contains
the original matching IDs and crop paths; synthetic records remain identified.
The overall planner/MCP operation has a 60-second deadline, one validation retry,
two model requests maximum, and bounded context/output. Large context is an
explicit error, never silently truncated vocabulary.

Rule events use their nested event zone. If otherwise matching observations have
no zone metadata, a zone query asks whether to count across all zones; it does not
misrepresent unknown locations as zero matches. Independent validation rejects
unrequested periods, a mismatched numeric duration, unsupported unique counts,
and unknown project vocabulary. These checks reject model output; they do not
generate a keyword-based substitute answer.

## Diagnostics

Each query has a separate diagnostic operation. Each actual local model attempt
and business tool call is captured over MCP and exported as a local OTel span.
Queries do not change `agent-state.json`, annotations, candidates, or approval.
Interrupted calls remain visibly interrupted. The existing trace endpoint can
filter by query ID; `GET /projects/{id}/evidence-queries/{query_id}` returns the
typed record, and `POST .../evidence-queries/{query_id}/replay` validates and returns
captured results without model requests, database reexecution, or other effects.

## Validation scope

Deterministic query and authored-brief regressions exercise filters, timezones,
scope completeness, injection resistance, clarification, provenance, and MCP
transport. They do not measure language-model quality. Separately saved live
smoke results use the actual local planner with explicitly synthetic recorded
events; they do not demonstrate warehouse detection accuracy.

Validation on 2026-10-28: the combined agent/MCP suite passed 60 tests, including
24 authored pipeline briefs and 24 golden typed evidence interpretations. Ruff
and strict mypy passed for the owned modules. No complete live 24-brief model
benchmark was run.

`artifacts/semantic-evidence-live.json` preserves the final live local Nemotron
probe: **5 of 6** cases met their expectations. The two supported count examples
returned exactly 1,205 damaged-pallet observations today and one forklift
observation yesterday; unknown classes, unique-object counts, and missing periods
produced clarification. The custom inspection query for bent connectors over
48 hours returned an unhelpful clarification after validation rejected an
incorrect model interpretation. This remains a semantic reliability limitation
of the tested model; it did not execute an incorrect count. Earlier failed probes
are retained separately. The live probe left project state, record count, and
deployment unchanged. Further query prompt tuning was stopped to prioritize
the describe-to-build agent workflow requested by the user.
