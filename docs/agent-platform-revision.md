# Agent platform revision · 2026-10-28

## Product contract

The application is an orchestrator for building, testing, and operating a vision
workflow. A user states an outcome and supplies data. The orchestrator produces a
reviewable plan, chooses installed capabilities, executes bounded experiments,
shows each actual step and artifact, measures the result, and asks for human input
at evidence and approval gates. A preview is not an accuracy claim.

## Current implementation and gaps

| Area | Present | Missing for this product contract |
| --- | --- | --- |
| Harness | Durable build state, phase budgets, traces, replay, typed MCP client | Visible per-action timeline, plan artifact, capability discovery, versioned skill packages, capability health |
| Tools | Local project, block, preview, label, evaluation, training and evidence MCP tools | Search/source acquisition, model installation, segmentation, OCR alternatives, model comparison, dataset audit |
| Skills | Four short task hints embedded in `agent/skills/__init__.py` | Versioned Markdown playbooks with preconditions, tool policies, eval recipes and examples |
| Models | OWLv2, Apple Vision OCR/barcodes, Cosmos crop judgement, RT-DETRv2 training | SAM 3 adapter, YOLO adapters, additional OCR adapters and an installed/available/unsupported catalog |
| Evals | Planner cases, fixture regression, reviewed-label metrics and provenance | Cross-model same-data comparison, segmentation/OCR benchmarks, scene-disjoint holdouts, operational acceptance |

Earlier design documents list some proposed models as if they were available.
`docs/blocks.md` and the model registry define the executable boundary: there is
currently no segmentation block, SAM 3 adapter or YOLO adapter. Do not expose a
candidate as callable until it passes its adapter contract and hardware smoke test.

## Orchestration contract

1. **Discover and provision.** Read a machine-generated catalog of installed
   tools, models, versions, licenses, resource requirements and health. Install or
   enable only user-approved and compatible capabilities. Record exact weights and
   source hashes. Missing capabilities are explicit blockers or alternative paths.
2. **Plan.** A planner returns a typed `BuildPlan` with the goal, data assumptions,
   candidate workflows, required capabilities, proposed experiments, metrics,
   stop conditions and human checkpoints. Save and show the plan before execution.
   A model can propose steps but cannot grant itself capabilities or approval.
3. **Execute.** A separate executor consumes a validated plan revision. Every tool
   action records start, finish, input/output references, model identity, cost/time,
   errors and resulting artifact. Retries are bounded and idempotent. The UI shows
   the same events in a chronological timeline with live progress.
4. **Evaluate and decide.** Compare candidates on the same reviewed, held-out data
   and compatible output task. Show aggregate metrics, per-slice failures, latency
   and resource use. Select a candidate only when the defined gate passes; otherwise
   request better labels/data or a bounded improvement. Human approval controls
   training, recorded operation and external delivery.

Use separate schemas and persistence for `BuildPlan`, `ExecutionRun`, `ToolEvent`,
`Artifact`, `CapabilityManifest` and `EvaluationReport`. A plan revision is immutable
once execution starts. Changed goals, datasets, model weights or thresholds create
new revisions and invalidate stale comparisons.

## Tool and skill catalog

Expose tools through typed MCP servers grouped by authority: project/media,
vision inference, annotation, evaluation/training, evidence, and optional external
research. Each tool advertises task type, input/output schema, hardware support,
license, side effects and runtime readiness. The orchestrator grants only the
tools needed for the current phase. Web search and crawling, if added, are a
separate source-acquisition capability with source URLs, timestamps, licenses,
robots/access rules, and prompt-injection isolation; fetched pages cannot issue
agent instructions. Web findings do not substitute for image-ground-truth labels.

Store task playbooks as versioned `.md` packages, for example detection,
segmentation, reading, tracking and alerting. Each has a selection rule, required
inputs, allowed tools, expected output artifact, validation recipe, failure modes
and examples. A tested loader selects relevant playbooks and records their hashes
in the plan and trace. Markdown is guidance; executable policy remains in code.

## Model adapters and selection

Provide one adapter contract for detection, instance segmentation, OCR, barcode,
VLM and training. Normalize outputs with confidence, coordinates/masks, provenance
and timing. Candidate families include promptable SAM 3, installed YOLO variants,
OWLv2, RT-DETRv2 and OCR alternatives such as PaddleOCR. Selection is a measured
comparison for the requested task and reference hardware, not a fixed ranking.

SAM 3 is a valid promptable segmentation candidate. Its official repository
currently documents a CUDA prerequisite, so Mac MPS operation must be proven
separately or served from a compatible remote GPU with explicit data-transfer
consent. A model's existence upstream does not make it available in this Mac app.
YOLO implementations and weights need per-variant license checks before packaging
or use. OCR candidates must be scored on the actual text types, languages, image
conditions and exact-match rules of the project; Apple Vision is only a baseline.

## Evaluation and test gates

* **Harness:** planner and executor contracts, tool authorization, budget and
  timeout behavior, crash resume, stale-plan rejection, replay without duplicate
  effects, and UI timeline consistency with stored tool events.
* **Agent:** frozen goal and refinement suites with required-plan fields,
  capability choice, calls, failures, latency and semantic fidelity. Run real model
  and MCP calls separately from deterministic fixtures.
* **Vision:** task-specific reviewed data with scene-disjoint holdout; detection
  precision/recall and count error, segmentation mask IoU and instance metrics,
  OCR character/word error and field exact match, plus failure slices by camera,
  lighting, scale and occlusion. No model promotion from correlated frames alone.
* **System:** reference-hardware memory, latency, sustained throughput, model
  coexistence, offline behavior, native UI, live source permissions and alerts.
  Report a pass only for the exact tested capability and environment.

## Build order

1. Introduce capability manifests and an accurate UI catalog of installed,
   available-to-install and unsupported tools/models.
2. Persist a typed plan and separate executor; emit durable per-action events and
   show them prominently in the native conversation.
3. Move task hints into versioned Markdown skills with loader and contract tests.
4. Add adapter slots and provision one new model family at a time, starting with
   the task that has representative reviewed data. Benchmark SAM 3 on supported
   hardware, a YOLO variant, and an OCR alternative before selecting defaults.
5. Expand the eval harness and acceptance datasets, then add optional web/source
   acquisition with provenance and isolation.

This is an architecture change proposal, not a claim that these capabilities are
already implemented.
