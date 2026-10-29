# Implementation status

The product is an adaptive application builder: the user supplies an objective
and media; the agent discovers tools, runs experiments, examines actual results,
and changes its approach toward a working application. The
[revised direction](agent-builder-proposal-2026-10-29.md) supersedes the earlier
two-workflow-family framing. A0, the real observation-to-action loop, is the next
milestone. The proposed time boxes are not accepted delivery commitments.

## Current software checkpoint

The composition foundation generates typed connected workflows with per-node
model bindings, static crops/resizes, parallel readers and visible text comparisons
independent of event recording. Conversational preprocessing edits preserve model
bindings and preview the changed pixels before committing. See
[composition](compositional-authoring.md), [refinement](preprocessing-refinement.md)
and [evaluation boundaries](compositional-evaluation.md).

The [full base+dev suite](../artifacts/compositional-authoring/full-tests-final.log)
passes **1,137 tests with two optional skips** in 398.80 seconds. Strict mypy passes
on 184 source files for macOS and Linux; Ruff passes. Debug and Release native
binaries each pass **257 checks**. The installed engine source is
`d76d7e7d6b91f28605917393e63e94eccc37f9099e9382a684b04daec751a552`.
[Bundle relocation](../artifacts/compositional-authoring/bundle-verification.json)
passes isolated imports, actual native OCR and signature checks.

[Actual local-planner evidence](../artifacts/compositional-authoring/README.md)
includes connected crop → resize → OCR → comparison and parallel OCR/barcode
execution on generated software fixtures. These observations prove those
execution paths, not representative accuracy or adaptive investigation.

The [installed native walkthrough](../artifacts/compositional-authoring/native-ui.json)
visibly built the left-half workflow, then applied a conversational change to the
right half at 900×300. Actual OCR changed from `ABC-990` to `WRONG-111`; the visible
comparison changed from Pass to Fail, with the corresponding source-image region.
Initial and refinement model calls took 44.91 and 23.32 seconds. The original
project's checked files are unchanged. The new project remains unreviewed, with
no evaluation, events or deployment approval. Earlier file-picker automation
timeouts are retained; reconnecting to the canonical app recovered the walkthrough.

**The installed builder still asks for a graph and then runs a prescribed host sequence.**
It does not return experimental results to a continuing model that chooses its
next experiment. Static graph composition is groundwork for A2, not completion of
A0–A3. Data-dependent object crops, per-object joins, application view synthesis,
unseen-task generalization and the wider release requirements remain open.
The [A0 implementation plan](a0-implementation-plan.md) names the loop, tool and
persistence changes needed next; it is not an implementation claim.

### Experimental A0 checkpoint: `4ef0673`

The published source now has a separate durable investigation runtime. It captures
one model-selected action, executes discovery/media inspection/provisional vision
inference through MCP, and returns the actual observation to the next model call.
The model can request a workflow, receive its compiled preview, and select the
exact previewed revision as a draft. Pause/resume/cancel, cumulative budgets,
source ownership, development-data exclusions and immutable receipts are enforced
by the host. This path does not approve deployment or mark annotations reviewed.

A scripted integration test executes the complete workflow path in an owned
worker and checks that existing project candidates, labels and events survive.
The local llama backend's actual chat template/tokenizer is checked before model
requests; other compatible servers explicitly use an estimated budget. Oversized
preview details remain retrievable as saved observations.

The [GitHub CI run](https://github.com/manavmodi22/Vision-Agent/actions/runs/40922692488)
for commit `4ef067339a9f8c7de3b3c7f4d2b91a4e6b0824aa` passed **1,285 Python tests
with two optional skips**, Ruff, strict mypy on 199 files, and 291 native checks.
The local Release binary passed **293 checks** including the retained Run4 and
Run5 snapshots with actual OCR; see the [release receipt](../artifacts/a0-investigation/native-release-20261029T174028Z/report.json).
These checks validate software contracts, not the agent's ability to finish a task.

**A0 is not yet accepted.** The first three actual local-planner runs failed to
reach a vision probe because discovery/documentation was not usable enough. The
fourth and fifth reached actual Apple OCR but exceeded the then-active 8K context
budget on the next request. After bounded result projections and a verified 16K
window, the Qwen3-14B baseline still failed: it ran no vision inference, repeatedly
searched detection capabilities, and asked the user to choose a model after
626 seconds. The [complete baseline trace](../artifacts/a0-investigation/qwen14-16k-baseline/report.json)
is retained. The Qwen3.5-9B candidate ran actual OCR and an empty barcode probe,
then asked for crop coordinates already present in earlier OCR evidence. It also
produced no draft. The [comparison](../artifacts/a0-investigation/MODEL-COMPARISON.md)
records both failures and the resource change that prevents a controlled speed
ranking. The default model is unchanged. Earlier traces and subsequent fixes remain in the
[evidence index](../artifacts/a0-investigation/README.md).

The development native app now has session-bound investigations, durable controls,
actual probe regions/readings and exact draft previews. Its retained four-reading
OCR observation was visibly verified, and a fresh goal was submitted through the
composer. The canonical app remains at the composition checkpoint; experimental
investigations do not yet hand drafts into the existing review/deployment flow.

### Previous text-region checkpoint: `3751`

The text-region authoring update adds drawing, four-corner editing, transcripts,
undo/redo and autosave to the contextual image editor. OCR/barcode predictions can
be explicitly copied into unreviewed labels after the source image hash is checked.
Users choose whether image-level expected values remain manual or derive from
region transcripts. Complete-label JSON transfer and dataset snapshots preserve
geometry, raw values and known model-exposure history; COCO remains object-box-only.
See [annotation contracts](text-region-annotations.md), [native editor](../app/text-region-editor.md)
and [portable labels](portable-labels.md). The [full base-dependency suite](../artifacts/text-region-authoring/software-validation.json) passes **848 tests with two optional skips**, strict mypy on 172 files for Linux and macOS, and Ruff.
[Debug and Release native builds](../artifacts/text-region-authoring/native-validation.json) each pass **242 checks**, including offscreen AppKit editing gestures. The [packaged relocation check](../artifacts/text-region-authoring/bundle-verification.json) passes isolated imports, actual Apple OCR and signature verification.
The installed engine source is `3751f55e26bb8f270c3bd38ba4c51c4081d833b57effde506653c3298b864e6b`.
Spatial text-localization scoring and the broader platform requirements remain open.

The [installed native walkthrough](../artifacts/text-region-authoring/native-ui.json)
built the three-image OCR workflow from a description using one local planner call
(60.754 seconds) and produced seven real reader observations with zero events.
It verified explicit prediction copying, a Cyrillic-to-Latin correction retaining
the original seed, transcript and geometry undo/redo, manual drawing, autosave and
navigation, expected-value projection, and native complete-label export/import.
The contextual sheet rejected coordinate dragging in the automation service;
the main Annotations view accepted the same canvas actions. This distinction is
retained in the evidence. Both edited images remain unreviewed. Returning to the
same conversation leaves evaluation gated on reviewed data. The original project's
four checked files remain unchanged. These are software acceptance examples,
not independent labels or measured product accuracy.


### Previous reader checkpoint: `e523`

The reader update adds actual Apple Vision text/barcode quadrilaterals, OCR
confidence, raw Unicode values and reader identity to the engine and native
preview. Corrections remain image-level expected-text annotations; text-region
geometry is evidence and is not yet editable/scored ground truth. Mixed OCR/VLM
workflows retain both kinds of output. Legacy CLI/evidence remain readable, while
fresh protocol-2 runs reject mismatched dimensions, policy and geometry.

New planning-options version 0.3 binds the selected OCR model explicitly; old 0.1/0.2
replay retains implicit Apple defaults. Unavailable readers reject without fallback.
The native Debug/Release builds pass [237 checks](../artifacts/native-reading-v2/native-validation-final.json), including actual captured payload decoding. The
[seven native image probes](../artifacts/native-reading-v2/report.json) retain real
regions, rotation/skew behavior, QR payloads and the known Cyrillic-X confusion.
The [isolated base-dependency suite](../artifacts/ci-baseonly/tests-final.log) passes
785 tests with two optional training skips. The CI Swift initializer defect and
mocked tests' accidental dependency on optional packages are corrected; fresh
remote CI evidence is recorded with the published checkpoint.

A [frozen public diagnostic](../artifacts/reader-evaluation/COMPARISON.md) ran both
readers on 100 original-size word crops: Apple 33 exact, isolated Paddle 16 exact,
zero execution failures. These are complete reader endpoints on cropped words,
not pure recognition, full-scene spotting or warehouse acceptance. Neither result
passes a product quality gate or changes the default. Paddle's [reduced runtime](../artifacts/adapter-probes/ocr-minimal/FEASIBILITY.md) is proven offline, including
an image-only OpenCV build, but remains unregistered: production worker lifecycle,
portable packaging, dependency notices and an approved installer are still pending.
The existing app's OpenCV native dependency audit also prevents a blanket
permissive-only runtime claim; model licenses and transitive binaries are separate.

The frozen engine source is
`e523a04b24594a48710c716c333763de3824e7d4c37cdaed58e196f9fcfacd3f`.
The [actual Qwen/MCP describe-to-OCR check](../artifacts/reader-evaluation/agent-e523.json)
passed with one response in 67.413 seconds, an explicit Apple reader, two public
images and 11 actual text observations with geometry. No events, reviewed labels,
evaluations or approval were created. Strict mypy covers 168 files in both base and
installed environments; the [CI portability receipt](../artifacts/ci-baseonly/validation.json)
distinguishes behavior-tested source from four AST-identical typing comments.

The [packaged relocation check](../artifacts/reader-evaluation/bundle-e523.json)
passed isolated imports, actual rich/native OCR, fixture gates and signatures.
The [canonical installation](../artifacts/reader-evaluation/package-installation-e523.json)
retains the previous app and the original project's checked files. A fresh native
walkthrough verified the installed engine, selected OCR regions/raw Unicode and
the exact-image correction editor with review unchecked and zero recorded events;
see [UI evidence](../artifacts/reader-evaluation/native-ui-e523.json). Earlier capture
failures remain recorded; successful later captures establish this specific flow.
No annotation was changed or approved during this walkthrough.

### Previous provisioning checkpoint: `2f08`

The previous provisioning candidate was frozen at
`2f0804da25ccbd6047d9dee2389127f13e3aa944b2596e1b0e7b577e1d5363a5`.
It fixes the deterministic event-intent guard's handling of adjacent `or`/`nor`
negation, preserving the original brief and conditional/conflicting instructions.
The [full suite](../artifacts/provisioning/full-tests-2f08.log) passes **758 tests in
391.25 seconds**; strict mypy on **168 files** and repository Ruff pass. The focused
initial-event and related suites pass 112 checks in 4.37 seconds. Unchanged Debug
and Release native binaries each pass **204 software/decoding checks**.

A [fresh isolated API installation](../artifacts/provisioning/installation-2f08.json)
verified pinned YOLOX artifacts, black-image inference, approval/hash checks and
job replay in **13.773 seconds**. The [exact original Qwen/MCP goal](../artifacts/provisioning/agent-2f08.json)
passed with one model response and actual inference on two unreviewed real frames
in **75.757 seconds**. [Bundle verification](../artifacts/provisioning/bundle-2f08.json)
passed relocation, isolated imports, OCR/fixture inference, actual YOLOX real-image
and black-image inference, and signature checks. [Native revalidation](../artifacts/provisioning/native-validation-2f08.json)
confirmed that a runtime change makes the old receipt “Not verified”; explicit
zero-download validation restored “Ready” while preserving the historical receipt.

The [native describe/build walkthrough](../artifacts/provisioning/native-agent-acceptance-2f08.json)
used one Qwen call (88.817 seconds), produced five preview frames and 20 unreviewed
annotation images, and opened the exact preview image in the annotation editor.
The new box-edit check is **incomplete**: the CUA ScreenCaptureKit service returned
an invalid-parameter error before an edit could be verified. Annotations remained
unchanged. No evaluation, accuracy, review or deployment approval is claimed.
The original project's four checked files remain unchanged; the public-data QA
project remains unreviewed in the app because UI control became unavailable.

[The canonical app copy and signature check passed](../artifacts/provisioning/package-installation-2f08.json), with the previous bundle preserved. A canonical relaunch UI check is not
claimed. See the [recipe and recovery contract](capability-catalog.md). These
checks establish the stated software and execution paths, not detector quality
or completion of the full architecture.

### Provisioning baseline: `f0d1`

The retained [baseline](../artifacts/provisioning/baseline-f0d1.json) at
`f0d1c365f956d3f57e11686ab58a1f7aa07a4595b2cb3f0b481a733a6a1451fb`
passes **732 tests in 426.56 seconds**, strict mypy on 168 files and repository
Ruff. Its [isolated API installation](../artifacts/provisioning/installation-f0d1.json)
verified official download hashes, black-image inference and job replay in 4.318
seconds. [Packaged relocation, ONNX smoke and signature checks](../artifacts/provisioning/bundle-f0d1.json)
and the [actual native installation walkthrough](../artifacts/provisioning/native-installation-f0d1.json)
passed, including closing/reopening the receipt and refreshing readiness. The
retained project's four checked files were unchanged.

The [exact Qwen/MCP goal failed](../artifacts/provisioning/agent-f0d1.json): the
first correct count-only decision was rejected because the guard misread “Do not
create events or send alerts.” The subsequent model turn asked an unnecessary
clarification. The [original operation](../artifacts/provisioning/agent-f0d1-operation.json)
and failure remain retained; the full described-goal path did not pass on `f0d1`.
The `2f08` correction and successful exact live rerun are recorded above; they do
not erase this retained baseline failure.

[Integrated parity](../artifacts/provisioning/adapter-parity-f0d1.json) matches all
30 retained outputs on synthetic NVIDIA frames with unreviewed published labels;
the diagnostic recall remains **52.7% (59 / 112)** and fails its gate. Installation,
parity and software checks do not promote model quality.

### Previous packaged checkpoint: `7f62`

Frozen runtime source
`7f621816c32bcfd849c3c1a8986aa86dbb72157e54b818455e24ed7384a41228`
passes **672 Python tests in 264.02 seconds**, strict mypy on **151 source files**,
and repository Ruff. Debug and Release native binaries each pass **173 checks**:
159 deterministic checks, 10 historical payload checks and four current API
fixture checks. These verify software behavior and decoding; the positive
acceptance fixture uses explicitly mocked inference and establishes no detector
accuracy. See the [full test log](../artifacts/evaluation-fairness/full-tests-final-7f62.log),
[integration receipt](../artifacts/evaluation-fairness/integration-validation-7f62.json)
and [native contract report](../artifacts/native-evaluation-validation.json).

The previously verified `7f62` package passed relocation, isolated packaged
imports, native OCR, fixture inference and signature verification. The
native walkthrough saved evidence assignments, re-evaluated in the same
conversation and checked explicit trial controls without changing annotations
or approving the QA app. See [packaged verification](../artifacts/evaluation-fairness/bundle-verification-7f62-final.json)
and [native walkthrough](../artifacts/evaluation-fairness/native-ui-qa-7f62.json).
These generated-fixture checks establish software behavior only. A separate
real-frame OWLv2 smoke executed and returned zero detections; it is not an
accuracy pass. Earlier live-model observations remain historical evidence below.

## Working development slice

- Machine-generated capability catalog separates installed, available-to-install
  and unsupported capabilities, with readiness, license/source provenance,
  requirements and schemas. Presence on disk does not claim successful inference.
- Reviewed provisioning for YOLOX-s ONNX: immutable source/hash/size/license plans,
  explicit approval, durable bounded jobs, streamed verification, atomic install
  and a fixed black-image smoke receipt. Stale or failed validation cannot keep
  the catalog callable. This CPU adapter supports exact COCO classes; installed
  model options still undergo vocabulary/task checks before planning.
- Per-candidate planning selects from compatible installed capabilities and saves
  the proposed model/reason and exact options before execution. Recorded training
  purpose distinguishes ordinary candidates from engineering or unknown local
  checkpoints; explicit experiments retain their separate request authorization.
  A training dataset hash or completed optimization is not reported as quality.
- Existing detection and native reading adapters emit common per-block evidence
  with model/artifact identity, input-pixel hash, measured total time and input-to-
  frame coordinates. Missing native geometry/confidence remains null. Content-
  bound caches and compiler identities reject changed model artifacts.
- Immutable build plans are saved before compile/preview and consumed by a
  separate executor. Actual start/finish events, artifact references and
  evaluation reports are durable; stale snapshots reject execution and replay
  cannot repeat effects. Versioned Markdown playbooks are packaged and their
  exact hashes are captured before the planner call.
- Agent-first home and workspace: describe a goal, attach media or use the public
  warehouse sample, then build beside a persistent conversation and actual preview.
  Durable build/continue routes coordinate planning, label review, evaluation,
  explicitly approved training and deployment. Expert tools are secondary.
- Conversational edits use the local model and typed patches against the existing
  graph: classes, confidence, count thresholds/duration, reading comparisons,
  sample rate and evaluation targets. Compound edits preview all affected
  candidates before commit; ambiguous requests preserve the app and ask for specifics.
- Spatial goals request actual region boundaries when absent. New projects have
  no invented lanes; saved geometry has confirmation provenance. Read-only OCR or
  barcode goals need no expected SKU, and count-only goals need no event threshold.
- Reading comparisons preserve exact versus substring matching and can emit only
  matching or mismatching results. Missing comparison values prompt for a literal;
  words such as “expected SKU” are not silently treated as the supplied value.
- Known email/webhook/MQTT setup requests pause conversational edits before any
  partial change. The capability question is recorded separately from model
  interpretation; an explicit vision-only answer can resume the edit.
- Agent evaluation shows candidate metrics, targets and failed examples that open
  directly for correction. Native region and expected-text corrections return to
  the same build.
- Candidate comparison freezes one validation protocol with compatible task and
  metric, every candidate fingerprint, reviewed membership, original-source/group
  assignments, policy and scoring recipe. Changes invalidate scores, active plans
  and approvals; duplicate bytes or decoded pixels cannot inflate sample counts.
- Human evidence configuration is available in the same workspace. Fresh media
  can be imported and reserved before model use, then manually labeled. Preview,
  proposals and training exclude reserved acceptance; one selected candidate is
  tested only through an explicit acceptance action. Exact captured-result replay
  performs no new inference. Renaming groups cannot manufacture source independence.
- Numeric success is separate from promotion eligibility. Unknown, correlated or
  synthetic samples require explicit `local_trial` consent and a reason, even
  when a target passes. Trial scope persists in evidence, is bounded to 500 frames
  per batch run and 3,600 seconds per live session, and disables external delivery.
  Legacy scores remain readable but cannot authorize a new recorded operation.
- Native dataset workspace with custom class ontology, image grid/filter, drawing,
  selection/move/resize, zoom/pan, undo/redo, revisioned autosave and review status.
  COCO import/export, image-byte snapshots and selected validation holdouts.
- Custom projects and editable typed block parameters/connections. The local agent
  receives dataset classes/stats; actual compiler and preview must succeed before
  a generated plan is committed. Human edits remain available beside agent help.
- Real OWLv2 proposals with source/model/image provenance; existing manual and
  reviewed labels preserved. Local Cosmos VLM crop judgement remains a hypothesis.
- Pretrained RT-DETRv2 custom training on MPS, safe checkpoint save/reload, lineage,
  reviewed-subset training and disjoint holdout scoring. Existing SSDLite models
  remain compatible. No automatic model promotion or deployment.
- Separate new-media runs for approved applications, preserving development data.
  Private Unix socket, atomic project files and SQLite evidence/crops/review.
- Explicit webhook/SMTP/MQTT configuration, Keychain credentials and durable bounded
  retries; actual loopback protocol receivers tested. No external recipient set.
- Durable agent operation/state, concurrent-input conflict checks, local OpenTelemetry
  traces and captured-result replay without repeated effects. Real custom planner
  request, OWLv2 preview, commit, reload and replay exercised.
- Strict schema/reference/port/DAG checks, safe count rules, model license registry,
  Apple Vision OCR/barcodes, measured evaluation and stale approval rejection.
- Public NVIDIA sample acquisition with provenance and a locally signed Mac bundle.
- Bounded camera, screen and timestamp-paced video ingress through shared memory.
  Actual native recorded-video replay is verified; camera/screen permission and
  hardware flows are not yet verified. Preview retains no recorded frames/events;
  normalized pixel exposure hashes prevent later copies from appearing untouched.
- Typed local-model evidence questions over complete-scope SQLite queries, with
  evidence records/crops. Five of six live semantic probes passed; one valid
  time-window phrasing requested unnecessary clarification rather than inventing a count.
- Relocatable bundled Python/dependencies, runtime identity validation, and parent
  process supervision. Ad-hoc local signing is verified; release signing is not.

## Remaining for the complete architecture

- Broader conversational reliability beyond the supported typed edit vocabulary.
  New arbitrary block topologies still need the workflow editor. Alternatives with
  different task scopes cannot be ranked together. Existing annotation proposals
  are retained across refinements so possible human corrections are not overwritten.
- Hardware verification of live camera and ScreenCaptureKit; RTSP and unattended
  continuous operation beyond bounded live sessions.
- Broader semantic question reliability and independent scene benchmarks.
- Core ML export, tracking/line-cross/dwell, tiling, segmentation masks and keypoints.
  RT-DETRv2 is the verified pretrained specialization backend; D-FINE/DEIM remain absent.
  Unsupported blocks reject compilation rather than pretending to run.
- Measured model selection and additional reviewed provisioning recipes. The
  planner chooses per-candidate models within typed workflow families; it is not
  a general code generator. YOLOX-s ONNX is integrated with one approved download
  recipe and actual CPU smoke/parity evidence. OWLv2/RT-DETR unified recipes need
  pinned multi-artifact manifests; dependency installation is not part of the API.
  Other YOLO variants and SAM 3 remain unsupported. PaddleOCR has a reduced image-only CPU runtime proof, public cropped-word
  diagnostic and runtime/license audit, but no callable production adapter or recipe.
  OCR expected-text correction is implemented; region-ground-truth editing/scoring is not.
- Representative independent acceptance data and broader task-complete recipes,
  failure-slice aggregates and standardized resource measurements. The protocol
  and promotion software gates are implemented; their tests are not evidence of
  vision quality. The standalone second-scene person benchmark failed the recall
  gate for all three tested detectors; it creates no app approval.
- Event correctness, false alarms and temporal-duration scoring. The current
  image recipe cannot promote rule/match/event-sink workflows; those remain
  explicit local trials with external delivery disabled. This gate therefore
  does not authorize their automatic webhook/SMTP/MQTT delivery. Explicit
  destination tests remain separate human actions.
- Representative, independently reviewed pallet/damage/label benchmarks. Public
  person/forklift samples do not validate those customer use cases.
- Release signing/notarization and CI on a dedicated Apple silicon runner.

No release milestone requiring the full five MVP flows is claimed complete.

Acceptance is limited to the user's declared scene coverage and recorded project
development, selection and training history. Human ground-truth review is allowed
before acceptance; model exposure consumes its untouched status. Unknown upstream
pretraining overlap and unseen deployment conditions remain outside that evidence.

## Historical checkpoints

The retained 24-case conversational-edit baseline scored 17/24 with the small
local planner. Explicit unit, metric and reading-value mismatches now reject
before mutation; this does not establish general language reliability. See
[the measured refinement report](refinement-quality-report.md). Stronger local
model comparison selected Qwen3-14B Q4_K_M provisionally for broader validation;
see [planner selection](planner-selection.md) for paired results and memory limits.

The platform foundation at source `d42048535b5d68e2dc863b265eb89415b60a056155567570b96b1ef5730caeee`
passes 540 Python tests. Strict mypy covers 130 runtime/evaluation source files;
repository Ruff passes. A targeted actual Qwen3-14B request for exact `ABC-990`
matching passed with one model call in 44.351 seconds; its plan predates compiler
execution and records the selected playbook hashes. This is one semantic case,
not a replacement for the retained full-suite model failures. See
`artifacts/stronger-planner/qwen14-platform-exact-reading.json` and
`artifacts/platform-exact-reading-execution.json`. Native packaging and interaction
evidence is reported separately; software checks do not establish general language
reliability or detector accuracy. A native real-warehouse build on the
preceding `c19fac507670` package compiled the requested people count and crop-event behavior, ran
five OWLv2 preview images, and paused at review of 20 unverified annotation rows.
No evaluation, recorded event, or deployment approval was created by that preview.

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
