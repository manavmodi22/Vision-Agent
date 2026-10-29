# Typed vision core

Owner: CV core. Public interfaces follow `architecture.md`. Spec 0.1 is a typed
JSON DAG; the compiler resolves references, topologically orders blocks, checks
parameters, ports, models, licenses and safe rule syntax before opening media.
Runtime processes bounded images or sampled video frames.

Data: normalized top-left xyxy boxes, polygon zones, project-relative image paths,
per-frame results. Canonical spec/dataset hashes bind evaluation to exact input.
Evaluation rejects empty or unreviewed labels and uses one-to-one label-aware IoU
matching for precision/recall; count error respects zones when supplied. Scoring
uses the classes and ancestor zone filters of the final detection-producing block,
matching `FrameResult.detections`. Unrelated ontology labels or zone branches do
not count as misses. Annotation zone tags are rederived from this branch's geometry.
Precision/recall require at least one selected positive after filtering; count MAE
can score reviewed all-negative images. The fingerprint still covers the full
annotation dataset, including labels outside the selected class scope.

Duration rules can be authored on independent images, but preview/evaluation warn
that they do not validate duration. Independent images use zero source timestamps
and fresh temporal state. Video and native live sessions preserve state across
their monotonic source timestamps; spatial evaluation is a separate evidence gate.

Fixture-color-v1 detects synthetic colored rectangles only, and every run warns
that it is synthetic. OWLv2 loads local cached weights only. Native OCR/barcodes
call the Swift Apple Vision bridge. Missing capabilities fail explicitly.

Tests cover graph cycles, invalid references/ports/params/rules, unknown models,
fixture box/count correctness, duplicate matching, empty/unreviewed eval and hash
stability. Real warehouse accuracy and model fine-tuning remain separate gates.
