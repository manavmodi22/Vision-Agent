# A0 investigation evidence

This directory retains exploratory results for the model-selected action loop.
The installed composition checkpoint remains separate. **A0 has not passed its
live acceptance criteria.** Scripted protocol tests are software verification,
not evidence that the local planner chooses useful experiments.

`run_smoke.py` generates a labelled software fixture with an item code and an
unrelated shipping label. It creates an isolated project, invokes the configured
local planner through the investigation manager/MCP path, and saves actual model
calls, actions and observations. The reference reading is evaluated outside the
planner context. This fixture is not a warehouse dataset or a quality benchmark.

| Run | Observed outcome | What it exposed |
| --- | --- | --- |
| [First failure](first-failure/report.json) | Three model calls, no vision probe; invented media ID rejected, then an unnecessary user question | Model-visible tool field documentation and inventory semantics were missing. The original harness also lost its completed task handle; the durable task record was retained. |
| [Second failure](second-failure/report.json) | Four actions, no vision probe; incorrectly concluded capabilities were unavailable | Requiring every natural-language search term hid valid tools. Source changed during this run; it is not frozen acceptance evidence. |
| [Third failure](third-failure/report.json) | Eight calls/actions, no vision probe; asked the user to explain available tools after repeated empty searches | Exact-token retrieval did not connect the chosen wording to catalogue descriptions. This run retained equal before/after source identity and took 265.70 seconds. |
| [Fourth failure](fourth-failure/report.json) | Actual Apple OCR completed with four readings; the next model request was blocked by the verified token limit | Full repeated geometry/artifact identities made feedback too large. Earlier malformed language and media-ID requests were rejected. Equal source identities were retained; 460.83 seconds total. |

The current fixes expose real catalogue facets and explicitly labelled search
suggestions, complete action/parameter documentation, saved-observation retrieval,
and bounded preview projections. The planner still chooses which action to take.

`full-tests-current.log` records **1,261 passed** in 516.66 seconds on source
`868861fddf5060f1c2749890aa1ad830ff8aa8c7ba49965ec0da0b689a8a9a12`.
`current-validation.json` states that this collection preceded the subsequently
added parent-death regressions. After their fixes, bootstrap metadata, exact
language/provenance schemas, fixture eligibility and compact probe projections,
`investigation-tests-final.log` records **132 passed**. Production Ruff and strict
mypy pass. The fourth run's next request shrank from 8,764 to **6,078 input tokens**
under the actual backend tokenizer, preserving the readings and explicitly
projecting geometry; full evidence remains in the task.

The development native app visibly displayed the fourth run's real OCR regions
and readings, then accepted a new goal through its composer. See
`native-ui-observations.json`; the new live trace is separate in `native-run/`
when finished. The canonical app was not replaced. A real positive trace,
evidence-dependent revision and failure/counterfactual acceptance pair remain
required. The earlier `full-tests.log` (1,202 passed, two skipped) validates an
older source, not subsequent changes.

The first native-started run is now retained in `native-run/`: it made one actual
OCR call after a rejected probe and repeated capability inspections, then stopped
at the 8K prompt limit (6,936 input + 1,400 output + margin). It did not create a
draft. Identical metadata snapshots and capability summaries are now deduplicated
in model context while all receipts remain inspectable.

The current planner policy has a 16K ceiling and still respects smaller verified
backend limits; unknown compatible backends retain the labelled 8K estimate.
The existing 14B planner and a hash-verified Qwen3.5-9B Q6_K candidate completed
the same generated case at 16K on frozen source `503a0468…`. Neither produced a
draft. See [the comparison](MODEL-COMPARISON.md) and both complete ledgers.
See `model-comparison-setup.json` and `qwen35-9b-qualification.json`. The candidate
is an explicitly labelled Unsloth conversion, not an official Qwen quantization;
the exact conversion-source commit is not established. Download, licence and
successful loading alone establish no planning-quality improvement.

Published commit `4ef0673` passed [GitHub CI](ci-4ef0673.json): 1,285 Python tests
with two optional skips, Ruff, strict mypy and 291 native checks. The local
[release check](native-release-20261029T174028Z/report.json) passed 293 checks
including the actual Run4 and Run5 snapshots. These precede the subsequent
discovery/context usability fixes.

The context fix collects three distinct observations before applying the limit,
so repeated capability metadata cannot displace the actual probe so easily.
Recent action arguments and repetition counts are exposed explicitly. The
[read-only replay](context-retention-replay.json) reconstructs calls 9 and 10 of
the 9B failure: the original requests lacked OCR coordinates; corrected requests
include them and fit the verified 16K budget. This is not a new model response
or a completed adaptive build. Discovery also separates probe eligibility from
installation readiness and distinguishes graph blocks from adapter models.

The [frozen public bus scene](bus-original-frozen/README.md) also failed to produce
a draft. Its actual OCR returned fourteen readings, but the automatic five-item
sample hid the destination from the planner. The revised size-based projection
keeps all fourteen without selecting them by task meaning. The reconstructed
[request fits at 9,405 input tokens](bus-size-projection-replay.json). Route 43 was
not recognized; retaining the destination does not fix that separate vision error.
The old-source degraded variant is explicitly postponed, not a passing case.

Three isolated next-decision diagnostics retain complete wire requests and
responses. With corrected context, [temperature zero repeated the empty barcode
probe and nonzero sampling asked for user guidance](next-action-replays/fixture-call10-pair-20261029/summary.json).
[Removing only the prior action-purpose prose](next-action-replays/fixture-call10-omit-purpose-20261029/summary.json)
changed the response to `prepare_workflow`. No proposed action was executed in
these diagnostics. The runtime now retains that prose in the durable task/UI but
supplies actual action arguments, outcomes and evidence to the next model call.
The subsequent [full investigation](evidence-context-live/README.md) executed an
empty barcode probe, then selected OCR and obtained all four actual readings.
It requested construction, but omitted the required source node and connected
text to an event input. The next response mistyped a supplied observation ID and
was rejected before execution. No workflow preview or correct draft resulted.
This is evidence of an observation-driven experiment change, not A0 acceptance.

The preceding `d8872ea` checkpoint passed [CI](ci-d8872ea.json): 1,303 Python tests
with two optional skips, Ruff, strict mypy and 291 native checks. The size-based
projection then passed 168 investigation tests; the subsequent omission of
prior rationale prose passed 49 focused context/projection/loop tests and strict
mypy. Exact scope and source identities are recorded in the corresponding logs
and [validation receipt](evidence-context-validation.json).

The next checkpoint adds grounded observation/workflow handles, explicit graph
semantics, omission of repeated preparation prose, and bounded saved-result pages
that preserve cursor scope and make progress. The final
[358-test integration run](grounded-contract-integration-tests.json) retained an
unchanged source identity; repository Ruff and strict mypy on 200 files passed.
The [paired workflow diagnostic](next-action-replays/workflow-call7-paired-comparison-20261029/README.md)
retains both incorrect model proposals and the actual failed preview of the 9B
graph. The [default planner was restored](default-planner-restored.json), and the
rebuilt development app [started a fresh native investigation](native-grounded-run/launch-and-start.json).

The [completed native test](native-grounded-run/report.json) made seven model calls,
six actions and two failed probe attempts, with zero completed vision probes and
no workflow. It asked for detector training labels for the text-reading task.
Source identity and the checked existing project files remained unchanged. The
native pause/restart/resume checks and [cancellation](native-grounded-run/cancellation.json)
are retained separately from that failed planner outcome. The raw ledger and
immutable artifacts were copied before cancellation; the reference was not sent
to the planner.

The [713046b CI failure](ci-713046b.json) is retained. Fix `16dcc52` restores the
legacy schema budget while keeping A0 documentation unchanged; its isolated
[validation](../a0-contract-docs-isolation/validation.json) includes all five
previously failing cases. This software repair does not change the failed model
qualification result.

The pinned gpt-oss candidate's [first full run](gpt-oss-qualification/first-live-failure/report.json)
stopped at a repeated reasoning-channel loop before any vision probe. Removing
the final-JSON grammar produced no usable final response. A separate captured
call using one native decision function returned a valid proposal; neither
diagnostic dispatched an action. The [review](gpt-oss-first-fixture-review/verdict.md)
keeps these boundaries explicit. The new optional decision-function transport
has [software validation](decision-function-validation.json), with defaults
unchanged; it still needs actual complete vision-task qualification.

The first full [function-transport trace](gpt-oss-qualification/function-live/report.json)
reached `draft_ready`, but its saved graph returned all four readings; successful
crop probes had not been incorporated. The exact selected graph and preview now
remain visible alongside recent experiments. Low and medium repeats still asked
for unnecessary clarification, so neither qualified. The [medium review](gpt-oss-medium-run-review/verdict.md)
and [next experiment](next-planner-experiment.md) separate model errors, missing
output primitives and documentation visibility.

The [workflow-visibility replay](gpt-oss-qualification/workflow-visibility-call7/receipt.json)
changes only generic operator/preparation documentation at the captured post-crop
boundary. It returned a valid construction-stage request in 46.29 seconds, with
unchanged historical state/evidence and no dispatch. Full-task qualification is
separate. [CI `08e3f46`](ci-08e3.json) passed 1,384 Python tests, two optional skips,
Ruff, strict mypy on 202 files and 322 native checks before this documentation change.

The [fresh workflow-visibility run](gpt-oss-qualification/workflow-visibility-live/report.json)
produced a real saved crop → OCR preview returning exactly `QZ-4817` in a
540.63-second session. Finalization was rejected because its evidence IDs omitted
the selected preview. Correct artifact output and incomplete agent handoff are
separate findings; no A0 acceptance is claimed. Historical media provenance
metadata is preserved with an explicit correction note in `capture.json`.
[CI for `e6340f3`](ci-e634.json) passed 1,387 Python tests, two optional skips,
Ruff, strict mypy on 203 files and 322 native checks.

The saved result is also [verified in the native app](gpt-oss-qualification/workflow-visibility-live/native-inspection.json).
Finish grounding now checks the exact selected-preview relation before dispatch
so malformed completion can receive bounded feedback. It does not substitute
IDs or remove the store's authority check. The generated-case harness supports
original/swapped layouts and now preserves truthful synthetic provenance with
fixture-only adapters disabled; historical metadata remains unchanged.

The [swapped-layout trial](gpt-oss-qualification/swapped-live/report.json) failed:
six real probes, no workflow, and a probe-budget stop after 435.70 seconds. The
agent located the correct side but truncated the code to `2Z-481` with overly
narrow horizontal crops. [CI `d8212a9`](ci-d821.json) passed 1,405 Python tests,
two optional skips, Ruff, strict mypy on 203 files and 322 native checks. Those
software results do not qualify the planner. The review-handoff and duplicate
probe audits are proposals, not implemented behavior in this checkpoint.
