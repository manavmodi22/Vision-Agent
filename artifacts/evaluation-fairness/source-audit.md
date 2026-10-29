# Candidate evaluation fairness — source audit

Audited source: `d403b8dc578b7be2b33b9b1065bbf90a288d01eb60cdd71dbd06b902b611428b`.
Scope: source inspection against `docs/agent-platform-revision.md`, not a new
accuracy benchmark. No runtime files changed, tests run, or inference performed.

**Conclusion:** the current implementation supports comparable, reviewed-image
experiments. It does not yet enforce the revised plan's scene-disjoint promotion
gate or provide a complete operational comparison report.

## Enforced today

| Boundary | Source evidence and practical scope |
|---|---|
| Same reviewed examples | `engine/service.py:193` requires 10–50 reviewed images, snapshots data/media, and rejects changes before saving. `agent/build_orchestrator.py:13` requires equal dataset hashes, metric and target. The hash binds annotation contents and image bytes (`engine/eval/hashes.py:95`). |
| Same detection objective | `mcp_server/builds.py:107` hashes selected classes, actual final detection-branch zone polygons, and rule/match parameters. `_evaluate_all` rejects divergent scopes and evaluates every candidate. Initial model-choice validation also requires a common pipeline task. Different detector models and confidence thresholds remain legitimate alternatives. |
| Frozen evidence | Saved plans bind workflow, data and model fingerprints. `engine/eval/hashes.py:38` includes detector weights/configuration, regions, and the new native-reading bridge/OS/request identity. Evaluation checks these again before returning; deployment and recorded runs recheck current evidence and explicit human approval. This is stronger than trusting a catalog alias. |
| Training separation | `engine/train/validation.py:8` rejects unreviewed data, byte-identical duplicate images, cross-split copies, and fixture training. `engine/jobs.py:99` keeps the active holdout out of training, then scores baseline and trained models on that holdout. |
| Honest measurements | Precision/recall use class-aware one-to-one IoU matching; counts use the final detection scope. Reading reports whole-image text-list exact match and bounded CER/WER with explicit normalization. Image-level failures are saved. None of these measurements establishes representative accuracy by itself. |

## Material gaps

1. **Scene independence is not an enforced gate.** The holdout is an image list,
   without scene/camera/time grouping. Large imports automatically use the first
   ten images; training defaults to the last ten when no holdout exists. Video
   sampling saves frame filenames but no durable source-asset/time grouping.
   Evaluation rejects duplicate paths, not repeated content; training only rejects
   exact byte copies, not adjacent or near-duplicate frames. Consequently ten
   reviewed correlated frames can pass a metric and reach `_scored`'s deployment
   recommendation. Existing warnings are truthful but do not satisfy “no model
   promotion from correlated frames alone.” Sources: `mcp_server/builds.py:131`,
   `engine/media.py:65`, `engine/datasets.py:229`, `engine/builds/manager.py:288`.

2. **The repeatedly inspected holdout is validation data, not a sealed acceptance
   test.** Labels/failure images are intentionally exposed for corrections and
   repeated threshold/model selection. Hashes invalidate old scores after edits,
   but there is no separate untouched scene-group test or selection-history limit.
   Calling the resulting best score an independent generalization estimate would
   overstate the evidence.

3. **Task and behavior evidence is incomplete outside initial planning.** Manual
   OCR and barcode candidates can share the same empty detection scope and match
   parameters, so the comparison signature itself does not distinguish those
   tasks. The evaluator scores text/detections, not event correctness: it resets
   temporal state per image and does not score sustained-duration rules, event
   false alarms, or named-field exact match. A passed detection/text target must
   not be presented as a tested temporal alert or field-extraction application.
   Sources: `mcp_server/builds.py:107`, `engine/eval/__init__.py:22`,
   `engine/eval/reading.py:43`.

4. **Failure slices and operating costs are missing.** Reports retain ranked
   image-level FP/FN/count/text failures, but no camera, lighting, scale, occlusion
   or class-slice aggregates/denominators. Frame execution measures time; evaluation
   discards it. ToolEvent duration includes orchestration/compile/inference work
   and is not standardized inference latency. There is no per-candidate cold/warm
   timing protocol, p50/p95, device/runtime capture, peak memory, or sustained
   throughput. Preview cache/order effects make raw tool-time ranking unfair.
   Sources: `spec/models.py:154`, `engine/eval/__init__.py:48`,
   `engine/runtime/executor.py:39`, `engine/platform/store.py:244`.

5. **Bind the full evaluation recipe in the next protocol.** The later common-
   adapter work binds adapter implementation, artifacts and dependency versions,
   but standalone `WorkspaceService.deploy/run` checks the spec and dataset
   fingerprints rather than an explicit evaluator/executor recipe version.
   Record and compare the scoring implementation and relevant runtime semantics
   before reusing approvals across upgrades. Likewise capture the effective OS/
   kernel for MPS execution, not only architecture, Torch version and provider.
   This is a follow-up source-audit finding, not a new tested failure or a claim
   that the existing plan snapshot lacks its broader runtime identity.

5. **Model choice lacks useful training evidence.** The successful two-model
   routing gate selected two local checkpoints with different initialization and
   training histories, but the compact planner context exposes neither. It even
   excludes the existing `limitations` field. Manifests contain training counts,
   lineage and explicit warnings; an evaluation-dataset hash does not establish a
   passing held-out result. See [manifest audit and minimal enrichment](model-option-provenance.md).

## Smallest implementation next

Add a **comparison evidence contract and scene-group gate**, retaining current
metrics and human controls; do not start another model integration to solve this.

* Persist image source asset hash/frame time and an explicit scene-group ID with
  provenance (`imported`, `human_assigned`, or `unknown`). Existing data starts
  unknown; never infer independent scenes from filenames or spacing alone.
* Freeze an `EvaluationProtocol` before comparison: dataset/group assignment
  hashes, candidate task/scope signature, metric/target, validation membership,
  independence status, and the intended evidence scope. Require every candidate
  result to reference that same protocol. Add OCR/barcode/output kind to scope.
* Return `evidence_scope` and `promotion_eligible` separately from numeric
  `passed`. Unknown/correlated/synthetic samples remain useful sample checks, but
  the agent requests representative independent groups instead of recommending
  quality-based promotion. Any explicit local trial override remains visibly
  distinct from an accepted model-quality claim and cannot manufacture evidence.
* Preserve current reviewed boxes and review flags. Group/split changes invalidate
  scores and approval; they do not relabel images. Independent group coverage must
  be an explicit task acceptance policy, not a magic minimum image/group count.

Then extend that same report with per-image measured latency and explicit cold/warm
policy, device/runtime identity, optional memory measurement with scope, and
slice counts/metrics. Missing measurements remain null. Reserve separate group-
disjoint acceptance data once iterative model tuning is complete.

Acceptance cases for the first slice: adjacent frames from one clip cannot become
promotion-eligible; renamed duplicates cannot inflate the sample count; unknown
legacy grouping stays a sample check; cross-split groups are rejected before
training; identical protocols compare all candidates; changed grouping invalidates
saved evidence; OCR-versus-barcode mismatch is rejected; no automatic approval,
label changes, or effect reexecution occurs. Add a temporal-event test protocol
separately before claiming event/hold-duration quality.
