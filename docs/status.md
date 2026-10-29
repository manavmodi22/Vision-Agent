# Implementation status

## Working development slice

- Machine-generated capability catalog separates installed, available-to-install
  and unsupported capabilities, with readiness, license/source provenance,
  requirements and schemas. Presence on disk does not claim successful inference.
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
  hardware flows are not yet verified. Preview retains no recorded event data.
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
- Measured model selection, unified provisioning and additional adapter families.
  The planner chooses per-candidate models within typed workflow families; it is
  not a general code generator. SAM 3, YOLO and PaddleOCR are not callable in the
  app. YOLOX and PaddleOCR have actual isolated CPU probes, with runtime/license
  and packaging work still required for integration.
- Enforced scene-group promotion gates, separate untouched acceptance data, task/
  event-complete comparisons, failure-slice aggregates and standardized resource
  measurements. The standalone second-scene person benchmark failed the recall
  gate for all three tested detectors; it creates no app approval.
- Representative, independently reviewed pallet/damage/label benchmarks. Public
  person/forklift samples do not validate those customer use cases.
- Release signing/notarization and CI on a dedicated Apple silicon runner.

No release milestone requiring the full five MVP flows is claimed complete.

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
