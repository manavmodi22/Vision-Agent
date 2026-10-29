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
