# Independent swapped-layout audit

**Outcome: inconclusive; no workflow or selected preview was created.** This run demonstrates some observation-driven adaptation, followed by harmful crop choices and probe-budget exhaustion. It is not a successful application build or an acceptance pass.

Audited the original run and retained copies without inference or production edits. `report.json` matches its original bytes, SHA256 `b9d8d0ec9b3d59338bb8e7d86de8f8e4c10ee844381d2ccbb4cd4c32c58ab9f2`; retained `task.json` SHA256 `f6670586c6a5a2e3fdbcdca41f1103221db6bb6e3e4a99773f199d3f9447974c`. All six saved probe result artifacts were read and their recorded hashes verified.

## Recorded result

- Source before/after is exactly `a900515d20cb83d6a490e8f35c6389e284388e8ef4607d9e56c9c67b38252bd3`.
- 435.70 seconds; 9 captured model calls, 8 reserved/completed actions, 6 actual probes. Terminal reason: `Investigation probe budget exhausted`.
- `selected_workflow_revision=null`, `preview_observation_id=null`, project candidates empty. No `prepare_workflow`, `construct_workflow` or `finish` action occurred.
- Report reference result is `exact=null`, with no actual preview texts. It is unavailable because no preview exists, not a false claim that an empty output matched the reference.
- The source image is the verified swapped PNG `2289362dd7a70575521f0803830d9411fc97c0cd5b60784f88368c548949a708`. Persisted project metadata is truthful: `synthetic=true`, `fixture=false`, and generated/preexposed development provenance. All probe evidence identifies the actual `apple-vision` adapter/model with `system_framework_versioned` identity scope; no synthetic detector was used.

## Adaptation and failure boundary

| Executed action | Actual result | Assessment |
| --- | --- | --- |
| 3: Full-image OCR | Four readings: shipping header/value on the left; item header/value on the right | Correct available evidence for the changed layout. |
| 4: Right-column crop `[0.527344,0.158,0.700521,0.491667]` | `ITEM CODE`, `QZ-4817`; code geometry unavailable in this specific cropped inference | Cites action 3's observation. The model changed spatial strategy for the right-hand field, rather than reusing the earlier original-layout left crop. |
| 5: Full-image barcode | No items | An actual unsuccessful experiment, consuming one probe. |
| 6: Same right crop, then resize to 500×300 | Both texts, now with valid mapped geometry | Additional evidence was produced: the code's source-frame box is `[0.5317225,0.3815467,0.6993075,0.4877867]`. |
| 7: Crop `[0.55,0.3,0.68,0.5]` | `2Z-481`, missing geometry | Crop excludes both horizontal ends of the previously observed code. Its saved image visibly clips the first and last characters. |
| 8: Crop `[0.55,0.38,0.68,0.5]` | Again `2Z-481`, missing geometry | Changes only the vertical boundary, leaving the harmful horizontal bounds unchanged. This is a different request/pixel region, not an exact canonical-action duplicate. |

The exact model context preceding action 7 contains the correctly mapped, rounded source box `[0.531722,0.381547,0.699307,0.487787]` and literal `QZ-4817`. The new crop starts to its right and ends to its left. There is no observed host coordinate-mapping defect at this boundary; the trace establishes a harmful crop choice, not the model's internal reason for choosing it. Confidence 1.0 on the later incorrect OCR reading does not establish correctness.

## Last request and authority

Model call `64915286e39b4f5da4c28630abd194f3` returns a typed, correctly grounded `run_probe` at revision 16, requesting full-image OCR again with `based_on_observation_ids=[]`. Offline DTO/grounding validation passes. Its normalized action is exactly equal to executed action 3, canonical hash `bc14ec47a919ad7687cb99b219c51c4f41f6b247734257f232da7c27dcc645b1`.

The captured context already reports six of six probes consumed. The host rejects this seventh requested probe before reservation: there is no action linked to the final model-call ID and no seventh inference receipt. This is correct budget enforcement. No finish decision or selected-preview citation was attempted, so this run does not exercise or validate the new finish-grounding behavior.

The existing repeated-action policy gap is relevant to the final request, but a duplicate guard alone would not prevent actions 7 and 8: their transforms differ. Reliable use of observed geometry and a decision to construct/assess a draft remain unproven here.

## Comparison scope

This is a deliberate **generated development counterfactual**, with preexposed content and an outside-planner reference. It is not a held-out accuracy benchmark. It is also **not a strictly frozen original/swapped pair**: finish-grounding source and truthful project-origin metadata changed between the earlier original run and this one. The earlier run produced a correct saved preview but failed finalization; this run produced no saved workflow. Those facts cannot isolate a causal effect of layout alone or establish broad robustness.
