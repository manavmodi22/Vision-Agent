# Typed workflow composition

The initial planner now produces connected vision workflows from the description.
It can compose crop, resize, detection, counting and parallel reader graphs instead
of selecting a fixed detection or reading template. New decisions use version `0.2`: one to three candidates
containing typed nodes and references. Version `0.1` decisions keep their original
template reconstruction for replay.

## Interface and ownership

`spec.authoring.GraphCandidate` owns a bounded, discriminated node list and an
evaluation metric/target. Nodes expose only implemented operations: sampling,
static crop, resize, detection, OCR, barcode, saved-zone filtering, counting,
count rules, text comparison and local event sinks. The host binds the imported
source, evaluation set and saved zone path. Generated data cannot supply a model
file, source file, endpoint, credential, external destination or executable code.

`agent.graph_authoring` reconstructs a `PipelineSpec` and per-inference-block model
bindings from captured engine options. Every detector/reader must choose an
eligible capability. `CandidateModelSelection.block_id` is optional only for
historical plans; modern graphs require exact coverage. The executor validates
these saved bindings before calling the engine compiler and real preview.

Pure structure checks reject missing/wrong ports, cycles, duplicate IDs,
unconnected transforms, unbound models and ambiguous aggregate branches before
inference. The engine remains authoritative for runtime prerequisites and actual
compilation. Existing evaluation supports one detector/count aggregate; graph
authoring must not imply multiple independently scored detection branches.

Request guards follow each inference block's upstream image chain. A crop in the
barcode branch cannot satisfy a request to crop the OCR input; resize-before-crop
cannot satisfy crop-before-resize. Explicit dimensions, rectangles and image halves
must match. Ambiguous branch associations or unsupported transforms require a
clarification. Mixed graphs validate comparison literal, mode and local event
condition against the relevant reader instead of letting a detector bypass them.

Conversational crop/resize edits use the existing preview-before-commit transaction.
The immutable plan matching the pre-edit candidates supplies the original captured
model options and bindings. Changes to inference identity, source, model or class
compatibility cannot silently discard that evidence. See
[preprocessing refinements](preprocessing-refinement.md).

Text comparison observations are separate from local event sinks. A request to
compare and show a result without events retains visible pass/fail evidence and
does not create a sink. Annotation predictions and metrics never become reviewed
ground truth through graph generation.

## Validation and limits

This is graph generation, not yet an adaptive investigation loop. The host
gathers context, the model returns a graph, and the host compiles/previews it.
Actual preview observations are not currently returned to the same model for its
next experiment choice. The next milestone is [A0](agent-builder-proposal-2026-10-29.md):
model-chosen actions with persistent state and actual observations.

Regression tests cover exact graph reconstruction/replay, per-block model
binding and tampering, schema/type/cycle rejection, event opt-out, unsupported
blocks, actual crop coordinate propagation, and comparison outputs without events.
The acceptance harness in [artifacts/compositional-authoring](../artifacts/compositional-authoring/README.md)
exercises the actual local planner, MCP, Apple Vision, connected transforms,
parallel readers and a conversational change. Generated fixtures establish software
execution, not recognition quality on representative scenes. Native validation is
recorded separately from these transport checks.

The broader platform remains in progress. Detection-conditioned crops,
segmentation/tracking, arbitrary code, external acquisition, and quality claims
are not enabled by exposing this authoring schema. Structural conversation edits
must retain the existing preview-before-commit and invalidation behavior.
