# Agent validation · 2026-10-28

Earlier sections preserve their named historical snapshots. The complete Qwen3-14B
run on runtime `c19fac507670` is recorded in the final dated section below.

Actual local model: `visionapp-planner` (NVIDIA Nemotron 3 Nano 4B Q4_K_M via
llama.cpp, configured by the integration owner). Input media is explicitly
synthetic; none of these results measure warehouse detector accuracy.

A fully specified pallet goal completed in 9.50 seconds with
3 actual MCP calls: block catalog, compiler validation and
five-frame preview. Evidence: `artifacts/planner-complete-brief.json`.

API probes with actual model calls and MCP previews:

| Probe | Duration | Questions | Candidates |
| --- | --- | --- | --- |
| damage-complete | 7.20 s | 0 | 1 |
| labels-complete | 5.89 s | 0 | 1 |
| underspecified-capacity | 6.31 s | 1 | 0 |
| clarification-followup | 7.38 s | 0 | 1 |

The labels probe exercised the native Apple Vision subprocess through MCP. The
underspecified-capacity case asked one question and saved no candidate. Its
follow-up reused the saved conversation and compiled the user-specified threshold
of seven pallets. The project retained clarification_count=1.

An earlier model response silently dropped an unspecified full-lane alert and
returned a count-only pipeline. The deterministic completeness gate now asks for
capacity instead. That failed observation is retained in the probe report.
The local model initially struggled with complete graph JSON. The implemented
normal path uses compact typed pattern decisions and deterministic graph
compilation, with native JSON schema constraints and up to two validation retries.
There is no fallback from a failed local-model call to a template.

Evidence: `artifacts/planner-probes.json`. These were early functional probes,
not a deployment-accuracy claim. The newer custom-entry-point live benchmark
is documented below. `artifacts/pattern-benchmark.json` separately records
24/24 deterministic authored-pattern/compiler regressions.

Verification: 31 agent/MCP tests passed; strict mypy (15 source files) and Ruff
passed. Tests include actual MCP stdio initialize/list/call, a five-frame fixture
preview, rejection of agent self-review, imported-source constraints, stale
hashes, explicit human deployment approval and persisted budgets.


## Durable state and custom authoring validation

An actual custom application was built from saved `person` and `forklift` classes
and five imported NVIDIA warehouse frames using the installed OWLv2 model.
The local planner preserved confidence 0.25 and recall target 0.9, compiled one
editable custom graph and executed five inference previews. The preview returned
12 detections; these are predictions, not
verified labels or measured accuracy. Total plan/compile/preview time was
32.68 seconds on this run.

The originating API request committed its operation token atomically. Reloaded
state was `evaluate`, six correlated OpenTelemetry SDK spans were exported to
local JSONL, and effect-free replay reproduced the captured result while leaving
both project and event records unchanged. Evidence:
`artifacts/custom-agent-durable-live.json` (actual inference) and
`artifacts/durable-agent-live.json` (separate synthetic software probe).

The custom output schema excludes unrelated preset examples. Explicit metric,
confidence and ontology checks reject local-model semantic drift instead of
accepting unrelated candidates. Custom app graph choices include detection,
OCR and barcode reading; the app's editable graph remains the execution contract.
Model label suggestions stay unreviewed and the MCP suggestion tool does not save
or overwrite annotations.

Durability uses a cross-process lock, input fingerprints including ontology and
holdout, a random operation token, captured compiler/preview evidence, and exact
result compare-and-swap at commit. Interrupted owners and pending calls retain
old budgets and history. Saved evaluations and deployment files determine the
reconstructed lifecycle phase; model assertions cannot establish approval.

Additional verification: 42 agent/MCP tests passed, strict mypy (21 source files)
and Ruff passed. Actual MCP tests also reject a second concurrent owner.
Tracing currently instruments each planner request/retry and each dispatched
agent tool. A VLM request made internally by an engine block is enclosed by its
pipeline tool span; separate VLM subspans are not yet wired to this operation
recorder.


## Initial custom-goal live benchmark

The first complete run through the custom entry point finished **20/24 cases**
against the original checks. It used actual local model requests, captured MCP
calls, compilation, sample previews, and guarded plan commits. The run occurred
under shared local workload; its durations are observations, not an isolated
latency benchmark. Source corrections were made while its process was running,
so a fresh process and full rerun are required to validate the final source.

The baseline and original test definitions are preserved without rescoring:

- `artifacts/custom-goals-baseline.json` and `.log`.
- `artifacts/custom-goals-baseline-cases.json`.

| Baseline failure | Observed behavior |
| --- | --- |
| count-all-regions | Added a count-at-least-one event despite “No alerts” and used recall instead of count MAE. |
| count-one-region | Correctly selected lane B but invented a count-at-least-one event. |
| count-missing-capacity | Invented a full-lane capacity of one instead of asking for capacity. |
| ocr-metric | Omitted the supplied ITEM-882 value and asked the user for it again. |

A separate audit found that `damage-both` passed its original field checks while
adding unrequested saved regions. That pass is retained in the baseline; the
current nonspatial cases now explicitly forbid a zone filter. These are tighter
checks, not a retrospective change to the original 20/24 result.

The corrective guards require count-only output without invented events,
preserve whole-image scope when no spatial region is requested, ask for an
unspecified full-lane capacity, and preserve explicit literal comparison values.
Those guards cause a model retry or an explicit question; they do not fabricate
an inference or silently substitute an authored template.

All images are original geometric fixtures. Unsupported fixture classes use
actual installed OWLv2; OCR/barcode cases use the native Apple Vision bridge.
Each result records its detector adapter. This measures bounded authoring
behavior, not warehouse detection accuracy, event reliability, or temporal dwell
accuracy. No deployment is approved and `eval_metric_reached` stays null.

The targeted initial-goal retest passed **4/5** (`artifacts/custom-goals-retest.json`):
all four original failures passed, but the tightened `damage-both` case omitted
its requested evidence-event rule. Its unrequested region filter was gone.
Source hashes were unchanged during this retest; see
`artifacts/custom-goals-retest-source.json`.

**Required remaining correction identified during the frozen comparison run:**
the host currently detects missing alert/notify/full-lane behavior more narrowly
than explicit create-event, flag, or save-evidence behavior. A model can omit the
rule while its message repeats that it will provide the requested behavior.
The `count-capacity` and `count-duration` cases exposed this during the fresh run.
This is an intent-fidelity defect, not an acceptable model-quality disclaimer.
A stronger model passing the same prompts would not remove the need for a general
completeness check, including negation cases. The source remains frozen for the
paired comparison before that correction is applied and revalidated.


### Frozen source-consistent full run

The fresh process completed **20/24** on runtime `4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`. Every captured source file and the native binary had identical before/after hashes. Evidence: `artifacts/custom-goals-final.json`, `.log`, and `artifacts/custom-goals-final-source.json`. This remains a comparison baseline with the required event-completeness defect above; the filename does not certify product readiness.

| Case | Original baseline | Targeted retest | Frozen full run |
| --- | --- | --- | --- |
| count-plain | Pass | — | Pass |
| count-all-regions | Fail | Pass | Pass |
| count-one-region | Fail | Pass | Pass |
| count-capacity | Pass | — | Fail |
| count-duration | Pass | — | Fail |
| count-metric | Pass | — | Pass |
| count-missing-capacity | Fail | Pass | Pass |
| count-missing-regions | Pass | — | Pass |
| count-new-region | Pass | — | Pass |
| detect-person | Pass | — | Pass |
| detect-forklift | Pass | — | Pass |
| detect-components | Pass | — | Pass |
| detect-explicit-label | Pass | — | Pass |
| damage-carton | Pass | — | Pass |
| damage-both | Pass† | Fail | Fail |
| damage-crushed | Pass | — | Pass |
| ocr-read | Pass | — | Pass |
| barcode-read | Pass | — | Pass |
| ocr-match | Pass | — | Fail |
| barcode-match | Pass | — | Pass |
| ocr-missing-value | Pass | — | Pass |
| barcode-missing-value | Pass | — | Pass |
| ocr-metric | Fail | Pass | Pass |
| ocr-read-simple | Pass | — | Pass |

† The original `damage-both` check did not reject its unrequested region filter. It was tightened before the later runs. The baseline pass was preserved, not retrospectively relabeled.

The frozen run failed `count-capacity`, `count-duration`, and `damage-both` because the compiled graph omitted the requested event rule. `ocr-match` failed safely after the model omitted `expected_text` on all three responses, despite repeating SKU-001 in its message; the explicit-literal validator rejected those responses and no candidate was committed. The recorded operation is `.visionapp/custom-goal-final/projects/213faae503db4a65/agent-runs/709f4761aa374c5c8007698890649088.json`.

`artifacts/custom-goals-summary.json` records the same per-case results in machine-readable form. The original and tightened suites are not interchangeable scores; these small runs establish observed authoring behavior only.

## Post-comparison event-fidelity correction

After the frozen paired model comparison completed, the required initial-goal
checks were implemented. The earlier benchmark files and their pass/fail records
remain unchanged; they describe runtime `4f94…`, not this corrected source.

The planner now validates explicit create-event, flag, and save-evidence requests
against the typed count condition. It rejects a missing rule, a changed threshold
or comparison operator, and a dropped or invented hold duration. For example, a
model returning a threshold of one and a twelve-second hold for a request of
**at least eight for twelve seconds** is rejected rather than committed. Supplied
values cause model retry; the host does not manufacture a replacement decision
or ask for a number that was already supplied.

The compact initial contract includes `count_operator` with the six supported
comparisons and a default of `>=`; zero is a valid threshold. Compilation retains
the operator and zero instead of coercing zero to one. The bounded quantity check
supports numeric values and simple spelled quantities, with count thresholds
from zero to 10,000 and hold durations from zero to 3,600 seconds. Seconds/minutes
are converted explicitly. Conflicting conditions or unsupported conditional
negation require clarification rather than a guessed graph. An unspecified
“full” capacity still produces a question even if the model invents a capacity.

Count-only, no/without/don't/disable-event requests remain count-only. An explicit
local evidence event can coexist with “no external alerts”; the resulting local
sink has no external destination. Object names containing “event” or “flag” do
not themselves request event behavior. Plain goals default to one candidate;
additional candidates are reserved for requested alternatives or genuinely
different supported approaches. User-facing workflow summaries are derived from
the compiled graph, rather than repeating unverified model claims.

Verification performed for this correction: **56** focused event/decision/goal
checks passed; the related durable/planner/build/refinement run had **65** passes
and seven failures from one outdated fixture that staged an unrequested event.
That fixture was corrected to match its count-only brief, and all **nine** tests
in its file passed on rerun. The five owned runtime modules passed strict mypy
and Ruff. Tests executed actual CPU fixture previews for operator/zero behavior
and local-event/no-external-alert behavior. No live LLM or GPU calls were used for
these guard regressions. The integration owner is running the full suite;
selected-model full benchmark results are pending and must be recorded separately.

### Visible Home crop request correction

The actual Home example, “Find damaged cartons and save a crop for review,”
exposed an omitted evidence synonym after the earlier event guard correction.
The interrupted selected-model run against runtime `7cfbe90c` remains historical
partial evidence; it is not a full benchmark result. Save/record crop/frame
requests now require the existing presence rule (`count >= 1`) and local event
sink. No new storage mode or block type was introduced. An explicit request not
to save crops, frames, or evidence cannot be fulfilled by an approved run, which
retains local evidence; the planner now rejects that candidate and asks for
clarification. No-event/no-alert requests still suppress event triggers.

The exact Home example is appended as case 25, requiring `damaged carton`, the
presence rule, `sink_event`, and no region filter. The preceding 24 definitions
are unchanged and their historical results are preserved. A CPU fixture test
verified an actual 70×20 saved damaged-carton crop and a local rule event after
isolated synthetic evaluation and explicit test approval; preview saved no
events and an unapproved run was rejected. This tests software evidence behavior,
not real damage recognition. Focused crop/event/decision/goal checks passed
**71/71**, with strict mypy and Ruff clean. Fresh live model results must be
recorded separately against the corrected source.

## Complete Qwen3-14B initial suite · 2026-10-28

The corrected-source initial suite completed **24/25**, using the official
Qwen3-14B Q4_K_M GGUF through `visionapp-planner` on localhost:1234, llama.cpp
b11963, thinking disabled, context 8192, one slot. The full runtime identity was
`c19fac5076701e673f0f6cca843619382dd195d32fdf0bb5dc68f9488346b639` before
and after the run; the server process/command also remained unchanged. The GGUF
revision/hash and exact launch parameters are retained in
`artifacts/stronger-planner/model-provenance.json` and `production14.json`.

The original 24 cases scored 23/24. Appended case 25, the exact visible Home
crop-for-review example, passed with the required presence rule, event sink and
no invented regions. This is actual model interpretation, compilation and
fixture-preview evidence, not damage-recognition accuracy on warehouse footage.

One failure remains in this frozen result:

| Case | Expected | Actual |
|---|---|---|
| `ocr-missing-value` | Ask which SKU to compare against. | Built a pipeline comparing OCR text against the literal string `expected SKU`, with no question. |

The failure's goal was “Read these labels and compare them against the expected
SKU.” No concrete SKU was supplied. The graph-grounded summary accurately stated
the saved contains comparison, but the task interpretation was wrong. The run
must not be represented as 25/25. Initial OCR/barcode checks here verify supplied
literal values using contains behavior; they do not test exact matching mode.

Case p50 was **25.99 s**, maximum **71.61 s**, and total wall time **772.92 s**.
Kernel pressure stayed normal (level 1), with zero new swapout pages. The GUI was
quit early to remove duplicate detector residency; no competing model inference
was scheduled. These are observed application latencies, not hardware-isolated
speed claims. Cosmos remained loaded alongside the planner.

Evidence: `artifacts/stronger-planner/qwen14-final-initial25.json`, `.log`, and
`qwen14-final-initial25-evidence.json`. The failed operation is
`.visionapp/qwen14-final-initial25/projects/597cb1cfca6f480b/agent-runs/423bd531d627466bae5a4fe2a6d60dbf.json`.
The preceding two-case run on `7cfbe90c` was interrupted for the crop-intent gap
and is preserved as `qwen14-interrupted-7cf-initial24`, not a complete score.
The historical 24-case definitions are also retained separately.

The subsequent complete refinement suite scored 19/24: four request timeouts
and one unsupported-action interpretation failure. See
[refinement results](refinement-quality-report.md) and
[planner selection](planner-selection.md). Reading/task-fidelity corrections
and any targeted reruns must be recorded separately; this full result stays
24/25 on `c19fac507670`.
