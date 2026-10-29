# Conversational refinement verification

The original verification snapshot was frozen at packaged source identity
`4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`.
This is a development build with measured language-model limitations.
The later complete Qwen3-14B result is appended below with its own source identity.

## What is implemented

A follow-up is interpreted by the configured local model against the actual saved
graph, selected candidate, current goal, conversation, vocabulary and regions.
The output is a discriminated list of typed edits or essential questions. Changes
remain on the actual graph; they do not reconstruct it from a template. Exact
legacy confidence and familiar additive-class commands retain their explicit
fast path. The live benchmark calls the local interpreter directly, so none of
its language results come from that fast path.

Each actual model attempt and MCP action is persisted and traced. A batch must
match the captured validated model response. The engine compiles and previews all
affected candidates before a guarded commit. Goal edits apply to alternatives
coherently; confidence defaults to the selected candidate. Class additions retain
boxes and reset review flags. Comparison requires a common scope, rule behavior,
metric, target and reviewed holdout. Annotation review, training approval and
deployment approval remain human gates.

The build can resume after real region definition without repeating the user's
goal message. An explicitly approved target-miss deployment can resume from the
improvement state; the current selected candidate and approval evidence are
checked before any recorded run.

## Actual local-model results

The retained 24-case baseline used `visionapp-planner` at localhost:1234
(Nemotron 3 Nano 4B Q4_K_M in the configured server), original generated fixture
pixels, and two actual candidate graphs per case. It scored the intended final
graph, including unrelated fields, rather than requiring one syntactic patch
operation where equivalent edits produce the same graph.

- **17/24 passed** in `artifacts/refinement-live-baseline24.json`.
- **32 actual model calls** were captured, including retries.
- **14 cases executed real MCP previews**; successful ambiguity questions do not
  mutate or preview a graph.
- Every case retained no deployment approval and no recorded operating run.
- This is language/workflow evidence, not warehouse detection accuracy.

Seven baseline failures were retained:

| Case | Observed result |
| --- | --- |
| Remove a class | Interpretation exhausted validation retries. |
| Hold duration only | Correct intended duration, but redundant threshold fields reformatted an unchanged rule expression. |
| Upper-bound count rule | Interpretation exhausted validation retries. |
| One frame every two seconds | Returned 2 FPS instead of 0.5 FPS. |
| Recall target | Returned the target while omitting the requested metric change. |
| Expected text exactly | Interpretation exhausted validation retries. |
| Text contains a literal | Returned exact comparison instead of contains. |

The executor now preserves an unchanged numeric rule expression. General fidelity
checks reject contradictory explicit sampling units, effective evaluation metric
and target, text literals and comparison operators. They never create a repair
patch or silently substitute another provider. A model must produce a valid
response within two retries; otherwise the app remains unchanged.

Targeted live follow-ups are separate evidence, not a replacement for the baseline:

- `artifacts/refinement-fidelity-retest.json`: hold-only passed with actual
  preview; the sampling and recall cases exhausted retries safely instead of
  returning incorrect edits.
- `artifacts/refinement-text-guard-retest.json`: contains passed with actual
  native OCR preview.

A complete 24-case run on the final guarded source has **not** been claimed.
Do not combine these targeted results into a fresh aggregate score or present
the historical 17/24 as a source-matched comparison with another model.

## Deterministic verification

Nineteen focused integration, graph-preservation, conversation, region-resume,
approval, trace and deduplication checks passed. Thirteen additional explicit
value/operator fidelity checks passed. Strict mypy passed for 30 scoped modules;
Ruff passed. The root task owns the final full-suite total and packaged/native
verification. An earlier overlapping scoped run had one 40-second test timeout
under load; that exact test subsequently passed without relaxing the timeout.

Remaining limits are the configured model's interpretation quality, existing
supported block types and explicit resource budgets. Aggregate class counts are
not unique-object tracking. Detection/count/text evaluation does not establish
business-alert correctness. No actual warehouse accuracy, autonomous deployment,
or production readiness is asserted.

## Complete Qwen3-14B refinement suite · 2026-10-28

The first complete selected-model run finished **19/24** on runtime identity
`c19fac5076701e673f0f6cca843619382dd195d32fdf0bb5dc68f9488346b639`.
Official Qwen3-14B Q4_K_M was served as `visionapp-planner` at localhost:1234
by llama.cpp b11963, thinking disabled, context 8192, one slot. Source identity
and server command were unchanged before/after. The original 24-case definition
was retained; previews used generated fixture pixels and native Apple Vision
where applicable. This score measures language interpretation and saved graphs,
not real warehouse detector accuracy.

| Failed case | Failure class | Observed behavior |
|---|---|---|
| `confidence_percent` | Request timeout | The first LLM span exceeded the 25-second HTTP deadline; no graph commit. |
| `compound_rule_target` | Request timeout | A later compound count/hold/metric request exceeded the same deadline; no graph commit. |
| `insert_rule` | Request timeout | Rule insertion timed out before a decision was accepted. |
| `ambiguous_accuracy` | Request timeout | The ambiguity request timed out before a decision was accepted. |
| `unsupported_compound` | Semantic/fidelity defect | The model treated email as a detection class and falsely claimed an email alert had been added. |

The last failure is a substantive correctness gap. The request was “Raise
confidence to 0.6 and send an email whenever a pallet is detected.” The accepted
interpretation contained confidence 0.6, `add_classes: ["email"]`, and a local
count rule; it asked no clarification. The benchmark detected the mismatch and
did not execute the returned edits. That test behavior does not mean the runtime
had rejected the interpretation. No email, deployment approval or recorded run
was created. Trace:
`.visionapp/qwen14-final-refinement24/projects/ab4b48549c2a45cc/builds/ba813fb725bb4fb7bb30c066bb131021.json`.

The frozen limits were **25 s per model HTTP request / 90 s overall operation**.
Because one timeout happened on a warmed compound request, the issue is not
only cold start. Timeout correction must preserve an explicit overall bound and
be verified separately. These four failures remain failures in this full report.

Case p50 was **16.69 s**, maximum **45.07 s**, total wall time **492.79 s**.
Both planner and Cosmos remained available, memory pressure stayed normal
(level 1), and there were zero new swapout pages or resource aborts. No other
model inference was scheduled during the suite. Existing swap allocation was
not reset. Every case retained no approval or recorded operating run.

Complete raw evidence: `artifacts/stronger-planner/qwen14-final-refinement24.json`,
`.log`, and `qwen14-final-refinement24-evidence.json`. Model weight provenance and
launch parameters are in the same directory. The initial-goal suite on this
runtime separately scored 24/25; it is not combined into a generic accuracy score.

Upcoming unsupported-action and timeout corrections, and their targeted retests,
must retain separate source identities and reports. They must not retroactively
replace this **19/24** full-suite result or the earlier Nemotron **17/24** result.
