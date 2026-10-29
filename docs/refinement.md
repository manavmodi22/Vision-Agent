# Conversational refinement

`RefinementPatch` describes one bounded change; `RefinementBatch` composes up to eight into one transaction. The executor edits the actual stored graphs. It does not regenerate templates or discard authored resize, crop, regions, wiring, model choices, alerts, or annotation content.

| Kind | Fields | Default scope |
| --- | --- | --- |
| confidence | confidence in 0–1 | selected candidate |
| add_classes / remove_classes / replace_classes | classes | all candidates |
| count_rule | count_threshold, count_operator, hold_s | all candidates |
| expected_text | expected_text, optional match_mode | all candidates |
| sample_fps | fps in (0, 60] | all candidates |
| eval_target | eval_metric, eval_target | all candidates |

Explicit `scope` can select one or all candidates. Optional `block_id` resolves an existing block. Without it, the relevant block must be unique. Removing a class that occurs nowhere in the targeted detectors is rejected. Final detector class sets must remain nonempty. Closed-vocabulary detectors cannot acquire unsupported labels; normal compilation rejects them.

If a count rule is absent, an explicit threshold can add the supported rule and local event sink after one unambiguous existing count block. If a text match is absent, an expected string can add the supported match and sink after one unambiguous OCR/barcode reader. A newly inserted match defaults to exact comparison; an existing match retains its mode unless changed explicitly. Existing sink delivery settings are preserved. Missing or ambiguous inputs require clarification. No new runtime block types are introduced.

Every affected candidate is compiled and actually previewed on up to five imported images before committing any changes. Preview failure in any alternative aborts the batch. Rule duration on independent images remains unevaluated and produces the existing explicit warning; timestamped video/live input is needed to verify dwell behavior. Sampling FPS is a video/live setting and does not manufacture elapsed time across independent photographs.

The guarded commit compares all candidate/model hashes, full dataset and media hashes, ontology metadata, region files, holdout selection, and current project/approval documents. Concurrent edits abort rather than overwrite. All changed candidates are stored together in one project document. Under the workspace lock, ordinary write failures restore every modified authoring document and approval. Approvals are revoked before replacement; a process crash can leave partial authoring documents, but cannot retain a valid deployment approval for the changed app. This is a local multi-document transaction with failure rollback, not a crash-atomic database transaction.

Adding new detector coverage resets image review flags while preserving boxes, text labels, provenance, class IDs, and original ontology entries. Class removal never deletes human annotations or ontology. Review invalidation is computed from the final composed batch, so a temporary remove/re-add does not falsely invalidate reviews. Confidence, sampling, rules, and targets preserve annotation bytes. Every actual graph change invalidates previous evaluation/deployment evidence. A no-op preview keeps it.

Candidate selection must reject different detection/region scopes, behavioral goals, metrics, targets, or holdout evidence. Explicit single-candidate goal edits can therefore pause for clarification rather than select an alternative for an obsolete goal. Deployment still needs the existing human approval gate.

Verification: `tests/test_refinement.py` and `tests/test_refinement_batch.py` exercise real synthetic-detector previews, multi-candidate changes, fresh-review requirements, ambiguity rejection, failed-preview/write rollback, and concurrent graph/label/region/holdout/pixel edits. `artifacts/vision-verification/refinement-native-ocr.json` records an actual Apple Vision OCR preview after insertion of a text comparison; its generated text image is a test fixture, not an accuracy benchmark.
