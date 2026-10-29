# Updated platform requirements and evidence map

Source: `agent-platform-revision.md`, adopted by the user on 2026-10-28. This map
retains the full requested outcome; partial implementation is not completion.
The original five describe/build/prove/run/improve flows remain acceptance flows.

Current provisioning candidate source is
`2f0804da25ccbd6047d9dee2389127f13e3aa944b2596e1b0e7b577e1d5363a5`.
The [full suite](../artifacts/provisioning/full-tests-2f08.log) passes **758 tests in
391.25 seconds**, strict mypy on **168 files** and repository Ruff. Its coordinated-
negation correction also passes 112 focused checks in 4.37 seconds. Unchanged
Debug and Release native binaries each pass **204 software/decoding checks**.
[Fresh actual isolated installation](../artifacts/provisioning/installation-2f08.json)
passes in **13.773 seconds**. The [exact original Qwen/MCP goal](../artifacts/provisioning/agent-2f08.json)
passes with one response and two real preview frames in **75.757 seconds**.
[Candidate bundle verification](../artifacts/provisioning/bundle-2f08.json) passes
relocation/imports, OCR/fixture inference, actual YOLOX real-image/black-image
inference and signature checks. No accuracy or deployment approval follows.

[Native revalidation](../artifacts/provisioning/native-validation-2f08.json) verifies
stale receipt handling and explicit zero-download restoration of readiness. The
[native goal walkthrough](../artifacts/provisioning/native-agent-acceptance-2f08.json)
passes describe/build/preview: one Qwen call (88.817 seconds), five preview frames,
20 unreviewed annotation images, and the exact preview image opened in the editor.
The new box-edit check remains **incomplete** because CUA ScreenCaptureKit returned
an invalid-parameter error; annotations remained unchanged. The original project's
four checked files are unchanged, and the QA project remains unreviewed in the app.
[The canonical app copy and signature check passed](../artifacts/provisioning/package-installation-2f08.json), preserving the prior bundle; canonical relaunch UI is unverified.

The [retained provisioning baseline `f0d1`](../artifacts/provisioning/baseline-f0d1.json)
passes **732 tests in 426.56 seconds**, package relocation/ONNX smoke/signature
checks and the actual native installation walkthrough. Its exact Qwen/MCP request
failed the deterministic coordinated-negation guard; that failure and operation
are preserved below. These installation successes do not establish a completed
describe/build path or detector quality.

The previous packaged software checkpoint is
`7f621816c32bcfd849c3c1a8986aa86dbb72157e54b818455e24ed7384a41228`.
It passes **672 Python tests in 264.02 seconds**, strict mypy on **151 files** and
Ruff. Debug and Release native binaries each pass **173 software/decoding checks**
(159 deterministic, 10 historical payloads, four current API fixtures).
The installed `7f62` package passed relocation, isolated imports, OCR/fixture
inference and signature verification. A native generated-fixture walkthrough
verified evidence editing, same-conversation re-evaluation and explicit trial
controls. No release or full-architecture completion is claimed.

The user still describes an outcome, receives a built preview, corrects examples
or refines the application in conversation, and reviews measured evidence before
explicit operation. Group/split configuration and acceptance appear only as
contextual evidence checkpoints in that workflow.

| Requirement | Authoritative completion evidence | Current work |
| --- | --- | --- |
| Accurate capability discovery and health | Current machine catalog; adapter/prerequisite/smoke receipts; native catalog matches API | Machine catalog/API and prior packaged native catalog inspected; per-candidate model options/routing verified; request-bound training-purpose eligibility verified; unknown local checkpoints require an explicit model experiment |
| Compatible approved provisioning with source hashes | Reproducible installer, verified source/weight hashes, failure recovery and native result | First unified recipe is implemented for official pinned YOLOX-s ONNX: immutable plan, exact human approval, bounded durable job, streamed verification, atomic install and identity-bound smoke receipt. Actual isolated API install/replay and candidate package/inference checks pass on `2f08`; native runtime-stale receipt rejection and explicit zero-download revalidation pass. `f0d1` actual native download/install remains retained. Additional recipes and dependency installation remain pending |
| Typed plan saved and shown before execution | Persisted immutable revision precedes first execution event; native plan visible | Saved-plan ordering and immutable revision contracts pass; actual Qwen/MCP exact-reading plan captured |
| Separate bounded executor | Execution consumes stored revision; stale data/model/plan rejected; coded phase/tool authority tests | Phase, capability, snapshot and concurrent-action contracts pass |
| Durable action timeline and artifacts | Matching start/finish events and content hashes for actual calls; crash/replay tests; native timeline | Actual MCP events, artifacts, evaluation references and replay tests pass; packaged native timeline, plan and contextual correction inspected |
| Versioned Markdown playbooks | Packaged documents, typed metadata, exact hashes in actual plan/trace, selection and authority tests | Six packages ship in wheel; hashes captured in actual Qwen plan and verified before execution |
| Common adapter contracts and new families | Actual detection/segmentation/reading outputs with timing/provenance; per-adapter hardware smoke | Common evidence wrappers cover existing detection/reading plus integrated YOLOX-s ONNX CPU. Actual OWLv2/RT-DETR/native OCR runs and YOLOX black-image/30-frame parity evidence exist; segmentation, VLM/training parity and further families remain pending |
| SAM 3, YOLO variant and OCR alternative comparison | Licensed pinned weights, supported hardware, actual same-task benchmark artifacts | YOLOX-s ONNX is registered with exact COCO vocabulary, pinned official artifacts and a reviewed install recipe; integrated 30-frame outputs match the prior probe, including its failed 52.7% diagnostic recall. PaddleOCR remains an isolated CPU probe with transitive-runtime audit; SAM 3 and other YOLO variants remain unsupported |
| Comparable candidate evaluation | Same reviewed holdout/task, aggregate and failure-slice metrics, latency/resources, explicit selection gate | Shared immutable validation protocol binds all compared candidates, task/metric, reviewed membership, source/group/policy and recipe; changes invalidate results/approvals. Numeric pass is separate from promotion eligibility. Nullable CER/WER and EvaluationReport references retained; masks, named-field metrics, failure slices and standardized resource comparison pending |
| Reviewed scene-disjoint acceptance data | Provenance and split audit, independent reviewed labels, exact benchmark run | Human configuration/reservation and selected-candidate acceptance are implemented, with exposure history, source/pixel separation, duplicate rejection and exact cached replay. Positive path is software-tested with mocked inference, not measured vision quality. Real independent reviewed ground truth remains incomplete; retained public NVIDIA labels are unreviewed, and the separate second-scene detector benchmark failed its recall gate |
| Optional source acquisition | Isolated external tool authority; URL/time/license/access provenance; injection and content-boundary tests | Pending |
| System acceptance | Native flows, sustained throughput/coexistence, offline behavior, camera/screen permissions, approved alerts | Protocol-bound approval and bounded local-only trials remain enforced. Candidate `2f08` native goal→preview and exact-image editor opening pass; the new box edit is unverified due to CUA failure. Prior generated-fixture evidence-editing checks remain historical. Canonical relaunch, broader hardware and operational acceptance remain pending |
| Original local release requirements | Reproducible bundle, all required flows, signing/notarization and Apple silicon CI | Local ad-hoc bundle verified previously; release gates pending |

Historical live-model failures and software reports remain in `artifacts/`.
New contract tests do not replace model-quality or vision-quality benchmarks.
Each update must name its tested source identity and exact evidence scope.

## Reviewed provisioning baseline at `f0d1`

The [capability contract](capability-catalog.md) defines the first recipe and API.
The human reviews exact source URLs, artifact hashes/sizes, target, scoped license
and readiness before approving a saved plan. No model can self-authorize an
installation. Read/list routes do not execute; interrupted jobs require an explicit
retry, and changed plans/targets are rejected. Existing differing model files are
preserved. A current smoke receipt binds artifact, runtime, host and request
identity; failed revalidation clears current readiness without erasing history.

The [actual isolated installation receipt](../artifacts/provisioning/installation-f0d1.json)
records 4.318 seconds for download and black-image smoke, with approval/hash checks
and active/completed job replay. Weights come from the pinned official release and
are not redistributed. Apache-2.0 is the repository declaration; a separate asset
license was not found in the inspected release. This is not independent legal
verification or model-quality evidence.

The [adapter parity receipt](../artifacts/provisioning/adapter-parity-f0d1.json)
retains the previous predictions on all 30 synthetic NVIDIA Warehouse_016 frames.
Published labels remain unreviewed; recall is **59 / (59 + 53) = 52.7%**, with 97
false positives. The diagnostic recall gate remains failed and no application is
approved. The [37-check software report](../artifacts/provisioning/software-validation-f0d1.json)
uses mocked downloads/inference and is separate from these actual receipts.
The [baseline full suite](../artifacts/provisioning/full-tests-f0d1.log) passes
732 tests in 426.56 seconds. [Packaged relocation/ONNX/signature verification](../artifacts/provisioning/bundle-f0d1.json)
and the [native installation walkthrough](../artifacts/provisioning/native-installation-f0d1.json)
also pass. The native receipt survives close/reopen; catalog readiness refreshes
and the retained project's checked files remain unchanged.

The [actual Qwen/MCP request](../artifacts/provisioning/agent-f0d1.json) failed:
the guard rejected a correct first count-only decision for “Do not create events
or send alerts,” then the model asked an unnecessary clarification. The
[original operation](../artifacts/provisioning/agent-f0d1-operation.json) remains
retained. `2f08` narrowly corrects the guard; its exact live rerun and candidate
package/inference gates now pass as recorded above. This does not rescore or erase
the baseline failure. Additional reviewed model recipes, integrated alternative
OCR, SAM 3 and other YOLO variants remain incomplete.

## Evaluation evidence slice at `7f62`

The prior correlated-frame software gate is closed: a passing sample/validation
score cannot authorize promotion. A human can reserve fresh sources before model
use, review their ground truth, declare intended scope/required groups, and run
acceptance for one selected candidate. Preview, proposals and training exclude
reserved data; exposure includes in-memory live pixels without retaining preview
frames. Original-source, decoded-pixel and prior-use checks prevent renamed
copies or scene groups from becoming independent evidence. A changed candidate
requires fresh acceptance groups; viewing an exact captured result runs no model.

Promotion requires current protocol-bound acceptance and numeric success.
Unknown, correlated or fixture data can support an explicitly approved
`local_trial` with a reason, limited to 500 frames per batch run and 3,600 seconds
per live session. Trial evidence retains that scope and suppresses external
delivery. Historical reports are readable, but historical approvals cannot
silently authorize new recording. Scene/policy edits preserve annotation bytes
and review flags while invalidating active plans and approval evidence.

The image recipe does not measure event correctness, false alarms or temporal
duration. Rule/match/event-sink apps therefore remain local-trial-only, and this
quality gate does not authorize their automatic external alerts. Independent
coverage is limited to declared project development/selection/training history;
upstream pretraining overlap is unknown. No representative accuracy claim follows
from the software protocol or its generated/mocked fixtures.

Evidence: [full suite](../artifacts/evaluation-fairness/full-tests-final-7f62.log),
[focused integration](../artifacts/evaluation-fairness/integration-validation-7f62.json),
[before/after gate probe](../artifacts/evaluation-fairness/protocol-checkpoint-7f62.json),
[native contracts](../artifacts/native-evaluation-validation.json),
[packaged verification](../artifacts/evaluation-fairness/bundle-verification-7f62-final.json),
[native UI walkthrough](../artifacts/evaluation-fairness/native-ui-qa-7f62.json), and
[integration design and limits](../artifacts/evaluation-fairness/integration-design.md).

## Historical checkpoints

The frozen `d403b8dc578b7be2b33b9b1065bbf90a288d01eb60cdd71dbd06b902b611428b`
checkpoint passed 581 Python tests and strict mypy on 135 files. Its native model
proposal view passed 137 checks. Two actual local Qwen/MCP cases verified exact
reading semantics and two-model detector routing. The latter selected weak local
engineering checkpoints, so it is **not** evidence of useful model ranking.
That failure is retained in `artifacts/stronger-planner/qwen14-selection-warehouse-execution.json`.
The first relocation attempt hit intermittent extra OCR stdout; a diagnostic
retry passed. Later `e098` package verification and native preview inspection are
recorded below; the original failure remains historical evidence.

The source audit in `artifacts/evaluation-fairness/source-audit.md` identified the
then-open gate allowing numeric passes on correlated images to recommend generic
deployment approval. The `7f62` protocol/evidence slice above closes that software
gate. The audit and pre-protocol reproduction remain retained; independent
vision benchmarks and the wider architecture requirements are still incomplete.

The `19f6e4115389679538f934d77a778d9b752952d49fb8d7256b72b91f61028367`
checkpoint passed 640 Python checks, strict mypy on 146 files, Ruff, 148 native
checks (138 deterministic and 10 backend payloads), and relocated packaged
inference/signature checks. Actual two-model routing used OWLv2 and pretrained
RT-DETR on identical real images; their proposals remain unreviewed. Native
20-frame warehouse acceptance then exposed a 100-second planner transport
timeout before a plan was produced. That failed run is preserved under
`artifacts/agent-experience/adapter-release/native-timeout`; the checkpoint is
not a native-flow acceptance pass. The bounded transport fix was subsequently
validated at the `e098` checkpoint below.

The previously accepted packaged source was `e098c7f30c336ab8914ce584b6940795585847756be1d8d3608d260fbc02f77c`.
The isolated planner transport fix passed 28 focused checks; the preceding
`19f6` full suite passed 640. That checkpoint passed strict mypy on 146 source files
and Ruff. Its bundle passed relocation, packaged OCR/fixture inference and deep
signature verification, including after the native walkthrough. Native checks
then totaled 138 deterministic plus 10 backend payload checks.

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
full architecture is complete. The [versioned `e098` report](../artifacts/runtime-validation-e098.json)
preserves that checkpoint and its failed run.
