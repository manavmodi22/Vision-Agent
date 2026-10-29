# Evaluation scope for composed workflows

The current image recipe has one numeric gate per candidate. It can execute and
report diagnostics for a graph containing a detector and readers, or multiple
text-producing branches. A passing scalar target cannot qualify those independent
outputs together. The existing acceptance policy already rejects mixed inference
families; the shared scope policy also rejects multiple same-family readers and
explains the limit in diagnostic warnings.

`unscored_behaviors(PipelineSpec) -> list[str]` owns these reasons. Diagnostic
evaluation appends them to warnings and evidence reasons. Acceptance consumes the
same reasons before inference, so a successful text union cannot conceal a failed
reader or establish detection quality. OCR, barcode and VLM text outputs are
branches of the same aggregate text projection: the executor currently deduplicates
their strings. Composite and per-branch quality gates remain separate future work.

The task signature records local event sinks and the semantics of their source
branches, independent of generated block IDs. Comparison-only and event-producing
graphs, different comparison-to-reader associations, and different event routing
therefore cannot share one comparison protocol. Model choice, confidence and
crop/resize preprocessing remain candidate experiment details, bound by each full
spec hash rather than by the task signature. Cropping does not redefine ground
truth: the current evaluator still uses the reviewed full-frame labels and selected
classes/zones. A crop-specific task needs corresponding explicit authoring intent
and reviewed labels; it is not inferred from crop geometry.

Recipe version `reviewed-images-v3` and the existing recipe source hash invalidate
older scoring protocols without rewriting their saved reports. Historical protocol
documents remain readable. Fresh validation or acceptance must freeze a protocol
for the current recipe.

Tests use generated image fixtures and mocked reader outputs. They verify actual
runtime text union behavior, diagnostic warnings, blocked acceptance before model
use, event-source signature distinctions, ID-renaming equivalence, preserved
preprocessing experiments, and rejection of historical recipe protocols. They do
not establish model accuracy.
