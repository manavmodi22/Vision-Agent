# Diagnostic replay of one captured next decision

`replay_next_action.py` prepares or requests exactly one structured `NextAction` or `WorkflowDecision`, selected from
the captured task stage.
It does not execute the proposed action, reserve a model/action receipt, update a
task, answer a pending user question, approve a draft, or establish A0 success.
No model calls have been made as part of preparing this runner.

The default input is the completed Qwen3.5-9B generated-fixture ledger:
`.visionapp/a0-investigation/run-20261029T174252Z/workspace/projects/a895814b9a4d4284/investigations/b8356984efca48508eef49f3b543e6d7/task.json`.
Use `--ledger /absolute/path/to/task.json` to replay another captured investigation;
`--call-number` (alias `--call`) accepts any valid one-based call. Call 9 selected a barcode probe; call 10 asked the user
for cropping guidance. These historical outputs are comparison references, not
correct answers or instructions for the replayed model.

## Offline preparation

Run from the repository root:

```sh
.venv/bin/python -B artifacts/a0-investigation/replay_next_action.py \
  --call 10 --context corrected
```

Without `--run`, the runner performs no network requests or inference. It validates
the captured ledger, reconstructs the historical prefix, checks transport bounds,
and writes a new diagnostic output directory. The exact backend token budget is
explicitly marked unchecked until a live request is authorized.

`--context original` uses the exact captured model-visible context.
`--context corrected` invokes the current `investigation_context` projection over
an in-memory store containing only calls, actions and observations preceding the
selected call. It preserves the captured pre-call state, system prompt, action
documentation, schema, output allowance and development-media bootstrap. It does
not re-query today's catalogue or media, introduce future observations, or supply
task-specific hints. With default `--contracts captured`, historical system/schema/docs are kept exactly;
changes to current executable schema constraints cause an explicit failure.
Prose-only title/description changes are ignored by the compatibility check and
are never substituted into the captured schema. No `WorkspaceService` or writable repository is
constructed. The source ledger hash is checked again at completion.

## Explicit current-contract comparison

`--contracts captured` is the default and retains the historical system prompt,
output schema and action/node documentation. `--contracts current` is an explicit
changed-input diagnostic: it regenerates those inputs from current production
contracts and applies `DecisionGrounding` to the exact historical state revision
and observation IDs. The citable set is rebuilt only from prior captured model
exposure plus the selected context's visible observations; earlier-observation
index entries alone do not grant citation authority.
`known_workflow_revision_ids` is rebuilt only from completed, validated, successful
workflow-preview observations in that historical prefix. Empty history permits
only null parent/selected revision references; task IDs and future revisions are
never substituted. State, media bootstrap and
output allowance stay historical. `input-diff.json` records every input change;
receipts mark current contracts as a changed-input diagnostic, not a pure context
replay. With `--context original`, prior generated summaries and observations remain
intact. `--context corrected` adopts current projection rules, including any
explicit model-prose omission, and records those changes. No fixture-specific
prompt cleanup is performed.

Both decision stages are supported. For a captured workflow stage, the historical
2,600-token output allowance is preserved. Candidate validation also reports
pure graph structure validity separately from shape/provenance, without compiling,
previewing or dispatching the graph. The saved original call 7 has valid DTO shape
but fails structure validation because its source is missing.

The completed evidence-context run's call 7 was reconstructed offline at
`next-action-replays/workflow-call7-captured-offline-20261029/`. It is an exact
captured input (`input-diff.json` has no changes), with no network/model request.

## Coordinated live replay

Only run after the parent task releases the shared inference slot. The following
command permits one real request with the captured sampling policy: temperature
0 and no additional sampling override. It neither starts a server nor changes
server settings.

```sh
.venv/bin/python -B artifacts/a0-investigation/replay_next_action.py \
  --call 10 --context corrected \
  --model-url http://127.0.0.1:1236/v1 \
  --model visionapp-qwen35-qualification \
  --model-receipt artifacts/a0-investigation/qwen35-9b-qualification.json \
  --run
```

To test a separately labelled non-thinking sampling policy, explicitly add:

```sh
--sampling-json '{"temperature":0.7,"top_p":0.8,"presence_penalty":1.5,"extra_body":{"top_k":20,"min_p":0,"repeat_penalty":1}}'
```

This changes sampling only. Thinking mode remains the server's configured mode;
the runner does not inject chat-template overrides. Unknown options, nonfinite
numbers, invalid types and values outside bounded ranges are rejected. The only
accepted llama extras are `top_k`, `min_p`, `repeat_penalty`, `repeat_last_n` and
`seed`. An omitted override always retains captured temperature 0.

For each call point, compare original/corrected context under the same sampling
policy first. Then change only the explicit sampling policy. Repeated samples
need separate invocations/directories. A changed proposed action is diagnostic
evidence; its correctness still requires later authorized execution and preview.
Do not describe this as a completed investigation or a controlled speed benchmark
when server residency or other active workloads differ.

## Purpose-field omission diagnostic

`--omit-recent-purpose` removes only the `purpose` field from each
`recent_actions` row after original/corrected context reconstruction. All action
arguments, statuses, repeat counts, citations and observations remain unchanged.
`context-diff.json` records each removed value and the before/after context hashes;
the receipt records the explicit flag and count. This is a diagnostic-only option
and does not alter production projection or the source ledger. It rejects an
unchanged experiment when no purpose fields exist. Sampling remains captured
unless separately overridden.

## Recorded evidence

Each invocation creates a fresh directory under
`artifacts/a0-investigation/next-action-replays/`, or `--output-dir` if supplied:

- `request.json`: exact planned messages, structured schema and sampling.
- `wire-request.json`: actual SDK request body, written only immediately before a
  real completion request. Retries are disabled.
- `wire-response.body`: exact HTTP response bytes, including error responses,
  with their SHA256 and HTTP status in the receipt.
- `response.json`: complete actual response including usage/timings when returned.
- `candidate.json`: generated decision, shape/revision/evidence validation and an
  explicit `action_dispatched: false`; it does not claim executable authorization.
- `reference.json`: separate historical response/error; never supplied as a prompt.
- `receipt.json`: source/context/schema/request hashes, historical prefix IDs,
  explicit sampling policy, backend metadata, tokenizer-budget evidence and input
  ledger immutability. Optional model provenance is labelled a declared artifact
  reference; it does not independently prove which weight file the live alias uses.

The live preflight verifies the selected local model and context allowance using
the production tokenizer-budget check. Llama backends use their actual chat
template/tokenizer; generic compatible servers retain the existing explicit
conservative-estimate limitation. The planned output budget remains captured.
There are no implicit retries, action dispatches or resumptions. User-facing
questions generated by a replay are saved candidates and are not sent anywhere.

## Completed bounded diagnostic pair

The two explicitly authorized generated-fixture call 10 requests are saved under
`next-action-replays/fixture-call10-pair-20261029/`; `summary.json` contains both
actual decisions and timings. Both used the corrected context and the same source
identity and passed shape/provenance validation. Temperature 0 repeated the exact
previous barcode probe that had produced zero readings (84.16 s). The explicit
non-thinking sampler acknowledged the empty barcode observation and asked for
user guidance (41.75 s). Neither proposed a successful autonomous build. The
second request reused 8,167 cached prompt tokens, so elapsed time is not a
controlled speed comparison. No actions were dispatched; source and ledger
hashes remained unchanged, and the server was idle before, between and after
the two requests. One sample per policy does not qualify a better sampler.

A third, explicitly authorized call 10 diagnostic is recorded under
`next-action-replays/fixture-call10-omit-purpose-20261029/`. It retained captured
temperature 0 and removed exactly four `recent_actions[].purpose` fields. Full
request comparison confirmed no other change from the earlier temperature-0
request. The model selected `prepare_workflow`, acknowledging successful OCR and
the empty barcode result (87.04 s, 7,538 input tokens). This single candidate
supports the prior-rationale reinforcement hypothesis; it does not establish a
correct isolation strategy, constructed workflow, or A0 success. No action ran.
