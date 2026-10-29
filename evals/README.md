# Warehouse regression and planner benchmark

`warehouse_briefs.json` contains 24 cases across pallets, damage and labels.

Run deterministic authored-pattern regression:

```sh
.venv/bin/python -m evals.run_benchmark --mode templates \
  --workdir /tmp/visionapp-pattern-eval --output artifacts/pattern-benchmark.json
```

This checks the compiler and the authored pattern selected by `use_case`. It does
not interpret the brief with an LLM and is not evidence of planner quality.

Run the real local planner (load a tool-capable model first):

```sh
.venv/bin/python -m evals.run_benchmark --mode live --model YOUR_LOCAL_MODEL_ID \
  --workdir /tmp/visionapp-live-eval --output artifacts/planner-benchmark.json
```

The live run uses actual Pydantic AI calls and MCP validation. It records spec
validity, required pattern, calls, latency and every failure. Both benchmarks use
synthetic fixture inputs and leave `eval_metric_reached` null. Real warehouse
accuracy requires a separate reviewed dataset; no benchmark substitutes for that
deployment gate. Use `--limit 1` for a quick server smoke test.

## Custom authoring through the primary entry point

`custom_goals.json` exercises 25 plain-language requests through the actual
`custom` planner schema: global and regional counts, named regions, thresholds,
duration, missing capacities/regions, arbitrary detection classes, damage,
read-only OCR/barcodes, expected text, missing expected values, and the visible
Home example requesting a damaged-carton crop for review. The original 24 cases
remain unchanged in `artifacts/stronger-planner/custom-goals-7cf-original24.json`.

```sh
VISION_APP_BINARY=/absolute/path/to/VisionApp.app/Contents/MacOS/VisionApp \
.venv/bin/python -m evals.run_custom_goals \
  --workdir /tmp/visionapp-custom-goals \
  --output artifacts/custom-goals-current.json \
  --model visionapp-planner --url http://127.0.0.1:1234/v1
```

The native binary is needed for actual Apple Vision OCR/barcode previews. Each
case uses original geometric test images. Detection cases whose expected classes
are supported by the explicit color fixture adapter use `fixture-color-v1`;
other detection classes use the installed local `owlv2-base-patch16` model.
The report records the adapter per case. OWLv2 predictions on these generated
images are not ground truth and do not measure warehouse accuracy.

The benchmark checks the declared outcome, compiled fields, required/forbidden blocks,
and captured actual model calls. A pipeline result must also pass the planner's
real compiler/preview/commit proof. It does not score detector accuracy, temporal
alert correctness, or every possible natural-language implication. Independent
images cannot establish a rule's dwell duration. `eval_metric_reached` remains
null, and no case approves deployment.

Repeat `--case CASE_ID` to retest named cases; an unknown ID is an error. Keep the
full baseline, its original case definitions, failed-case retests, and any fresh
full run separate. Tightening a check changes the test definition and must be
reported rather than silently rescoring an earlier result. Latest run evidence
and remaining limitations are recorded in `docs/agent-validation.md`.

### Recorded custom-goal results

| Run | Passed | Evidence |
| --- | --- | --- |
| Original checks, historical baseline | 20/24 | `artifacts/custom-goals-baseline.json` |
| Four baseline failures plus tightened damage case | 4/5 | `artifacts/custom-goals-retest.json` |
| Fresh process, tightened checks, frozen source | 20/24 | `artifacts/custom-goals-final.json` |

The frozen run is bound to runtime `4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`; before/after source and native binary hashes match. Its remaining failures are missing requested event rules in `count-capacity`, `count-duration`, and `damage-both`, plus safely exhausted output retries for `ocr-match`. These are retained failures, not passing deployment evidence. The event-completeness check is a required remaining correction; another model passing the prompts does not remove that requirement.

Original test definitions remain in `artifacts/custom-goals-baseline-cases.json`; tightened definitions are in `artifacts/custom-goals-current-cases.json`. The complete per-case table and explanations are in `docs/agent-validation.md`, with machine-readable results in `artifacts/custom-goals-summary.json`.
