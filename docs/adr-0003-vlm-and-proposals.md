# ADR 0003: typed VLM judgements and unreviewed label proposals

Status: accepted implementation extension, 2026-10-28. Owner: CV core.

The existing spec 0.1 graph envelope and existing block contracts remain unchanged.
We register an additional executable `vlm_judge` block, using the same open block
type and typed-parameter registry mechanism. Old documents remain valid. New
optional `FrameResult.judgements` evidence defaults to an empty list, so old run
documents remain readable. No existing port or metric changes meaning.

Inputs: `image:image`. Outputs: `judgement:judgement`, `text:text` (the chosen
label), and `event:event`. A crop block can precede the judge. Text labels can
feed the existing match block and use existing exact-string `text_accuracy` with
`Annotation.expected_texts`; no detector boxes are fabricated for judgement.

`VLMJudgeParams` embeds the local URL, model name, prompt, allowed labels and
generation limits. Changing mutable app Settings does not change an existing
candidate's semantics: it must be rebuilt. Preflight checks the served model and
vision support, includes stable server metadata and any provable local GGUF and
projector fingerprints in evaluation evidence, and distinguishes metadata-only
identity from verified local artifact hashes. Unsupported/offline servers fail
explicitly. No detector, fixture, remote model or free-text fallback is used.

The vision client sends bounded image bytes to a loopback HTTP service only,
uses structured JSON output, validates labels and confidence, limits retries and
request time, and treats response text as data. Image instructions are not tools.

`propose_labels(spec,dataset,project_root,max_frames=50)` runs only the detection
chain on supplied project images. It preserves every reviewed annotation and
leaves generated proposals unreviewed. Proposal provenance records model/spec
identity, image hash and run time. The service owns atomic commit and concurrent
user-edit protection; this function returns a copy and never writes annotations.

Tests cover offline/wrong-model/text-only preflight, local URL restrictions,
invalid JSON/labels, bounded retries, crop evidence, identity-hash changes, and
reviewed-label preservation. Acceptance also requires actual local VLM inference
and OWLv2 proposals, explicitly recorded as unverified model hypotheses.
