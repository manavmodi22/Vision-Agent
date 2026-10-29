# Updated platform requirements and evidence map

Source: `agent-platform-revision.md`, adopted by the user on 2026-10-28. This map
retains the full requested outcome; partial implementation is not completion.
The original five describe/build/prove/run/improve flows remain acceptance flows.

| Requirement | Authoritative completion evidence | Current work |
| --- | --- | --- |
| Accurate capability discovery and health | Current machine catalog; adapter/prerequisite/smoke receipts; native catalog matches API | 73-entry catalog/API and packaged native catalog inspected; per-candidate model options/routing verified; request-bound training-purpose eligibility verified; unknown local checkpoints require an explicit model experiment |
| Compatible approved provisioning with source hashes | Reproducible installer, verified source/weight hashes, failure recovery and native result | Existing individual installers; unified provisioning pending |
| Typed plan saved and shown before execution | Persisted immutable revision precedes first execution event; native plan visible | Saved-plan ordering and immutable revision contracts pass; actual Qwen/MCP exact-reading plan captured |
| Separate bounded executor | Execution consumes stored revision; stale data/model/plan rejected; coded phase/tool authority tests | Phase, capability, snapshot and concurrent-action contracts pass |
| Durable action timeline and artifacts | Matching start/finish events and content hashes for actual calls; crash/replay tests; native timeline | Actual MCP events, artifacts, evaluation references and replay tests pass; packaged native timeline, plan and contextual correction inspected |
| Versioned Markdown playbooks | Packaged documents, typed metadata, exact hashes in actual plan/trace, selection and authority tests | Six packages ship in wheel; hashes captured in actual Qwen plan and verified before execution |
| Common adapter contracts and new families | Actual detection/segmentation/reading outputs with timing/provenance; per-adapter hardware smoke | Typed evidence wrappers for existing detection and reading adapters pass contract tests and actual OWLv2/RT-DETR/native OCR runs; segmentation, VLM/training parity and new production families pending |
| SAM 3, YOLO variant and OCR alternative comparison | Licensed pinned weights, supported hardware, actual same-task benchmark artifacts | Isolated YOLOX-s CPU and PaddleOCR CPU inference verified, neither registered; Paddle transitive runtime audited; SAM 3 unsupported on Mac pending hardware proof |
| Comparable candidate evaluation | Same reviewed holdout/task, aggregate and failure-slice metrics, latency/resources, explicit selection gate | Existing detection/reading gates plus nullable CER/WER and EvaluationReport records; masks, field metrics and slices pending |
| Reviewed scene-disjoint acceptance data | Provenance and split audit, independent reviewed labels, exact benchmark run | Public real/synthetic NVIDIA data retained; second synthetic scene Warehouse_016 acquired with fixed 30-frame protocol before inference. Automatic published labels remain unreviewed; independent real ground truth incomplete |
| Optional source acquisition | Isolated external tool authority; URL/time/license/access provenance; injection and content-boundary tests | Pending |
| System acceptance | Native flows, sustained throughput/coexistence, offline behavior, camera/screen permissions, approved alerts | Prior bounded evidence retained; expanded acceptance pending |
| Original local release requirements | Reproducible bundle, all required flows, signing/notarization and Apple silicon CI | Local ad-hoc bundle verified previously; release gates pending |

Historical live-model failures and software reports remain in `artifacts/`.
New contract tests do not replace model-quality or vision-quality benchmarks.
Each update must name its tested source identity and exact evidence scope.

The frozen `d403b8dc578b7be2b33b9b1065bbf90a288d01eb60cdd71dbd06b902b611428b`
checkpoint passed 581 Python tests and strict mypy on 135 files. Its native model
proposal view passed 137 checks. Two actual local Qwen/MCP cases verified exact
reading semantics and two-model detector routing. The latter selected weak local
engineering checkpoints, so it is **not** evidence of useful model ranking.
That failure is retained in `artifacts/stronger-planner/qwen14-selection-warehouse-execution.json`.
The first relocation attempt hit intermittent extra OCR stdout; a diagnostic
retry passed. Native stdout ownership and independent preview inspection are
being hardened before the next package.

The source audit in `artifacts/evaluation-fairness/source-audit.md` identifies an
outstanding product gate: current numeric passes on correlated reviewed images
can still recommend deployment approval. A scene-group evaluation protocol must
separate sample checks from promotion eligibility. No representative accuracy or
full-architecture completion is claimed by these software checks.

The `19f6e4115389679538f934d77a778d9b752952d49fb8d7256b72b91f61028367`
checkpoint passed 640 Python checks, strict mypy on 146 files, Ruff, 148 native
checks (138 deterministic and 10 backend payloads), and relocated packaged
inference/signature checks. Actual two-model routing used OWLv2 and pretrained
RT-DETR on identical real images; their proposals remain unreviewed. Native
20-frame warehouse acceptance then exposed a 100-second planner transport
timeout before a plan was produced. That failed run is preserved under
`artifacts/agent-experience/adapter-release/native-timeout`; the checkpoint is
not a native-flow acceptance pass. A bounded transport fix is being validated.

The current packaged source is `e098c7f30c336ab8914ce584b6940795585847756be1d8d3608d260fbc02f77c`.
The isolated planner transport fix passed 28 focused checks; the preceding
`19f6` full suite passed 640. Current strict mypy covers 146 source files and Ruff
passes. The bundle passed relocation, packaged OCR/fixture inference and deep
signature verification, including after the native walkthrough. Native checks
remain 138 deterministic plus 10 backend payload checks.

Actual native acceptance used the built-in 20-frame real NVIDIA warehouse sample.
A written goal generated OWLv2 and pretrained RT-DETR candidates with the same
count-MAE target. Both previewed; inspecting the same second sample showed 1
and 4 hypotheses, respectively. Switching cleared the old preview while loading
and left the approval candidate unchanged. Correct this image opened the exact
sample; a box resize autosaved and the user returned to the same conversation.
All 20 annotation rows remain unreviewed, with 0 stored events, no evaluation and
no deployment approval. See `artifacts/agent-experience/adapter-release/acceptance.json`.

The first native request timed out 100.7 seconds into model generation. The fix
allows 150 seconds for the initial model response while retaining the 180-second
planner and 900-second build budgets, without automatic retries. The native retry
passed in 109.6 seconds for its model call using cached prompt state. This exposes
a material latency limit; it is not a cold-start benchmark or evidence that the
full architecture is complete. `artifacts/runtime-validation-final.json` points
to the versioned report and preserves the failed run.
