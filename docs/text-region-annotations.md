# Editable text-region annotations

The contextual image editor is an authoring surface for the describe, build and
prove flow. Users can draw a rectangle, move its four corners to fit printed text
or a barcode, transcribe the exact value, undo/redo and save. This complements
object-box labels. Predicted regions remain separate until explicitly copied.

The shared `Annotation` adds `text_regions` (default `[]`) and
`expected_text_source` (`manual` by default, or explicitly `regions`). Each
`TextRegion` has a stable ID, exactly four ordered convex corners in normalized
oriented full-frame RGB coordinates, its derived bounding-box envelope, a nullable
transcript, and optional original model-seed provenance. These are labels, so
they do not have a detector class or confidence. Original scores can appear only
inside the retained seed observation.

A draft may have no transcript. Review requires every transcript to be complete.
Region geometry/transcript changes or a text-source-policy change clear review at
the server save boundary. The native editor saves edits before allowing a separate
review action. Seeds cannot be altered or stripped from an existing region, and
deleting that region does not remove known model exposure. Native undo/redo also
keeps changed labels unreviewed.

Image-level expected text stays manually editable for historical projects. An
explicit action previews the region transcripts before switching to region-derived
values. The server then derives that list in region order, preserving exact Unicode,
case, whitespace and repeated instances. The current workflow text output contains
unique strings; image-level text accuracy/CER/WER do not measure localization,
reading order or repeated-instance geometry. No spatial OCR-quality claim follows.

Copying a current prediction preserves the original observation, adapter/model IDs,
execution identity hash, input-to-frame transform, original image byte hash and
copy time. The transform is applied exactly once to produce the editable full-frame
quadrilateral. File previews now bind `source_image_sha256`: execution verifies
unchanged bytes, and the native copy action rechecks them. Historical previews
without that identity remain visible but require a fresh preview before copying.

The existing per-image GET/PUT routes and dataset revision provide optimistic
concurrency. Older clients may read labels, but cannot erase existing regions by
omitting new fields on save. The bulk save path has the same validation. COCO
replacement only changes object boxes and preserves text labels. Snapshot format 2
includes complete annotations and a portable all-label archive with historical
model exposure; legacy snapshot metadata still decodes. See [portable label
transfer](portable-labels.md) for its versioned format and HTTP routes.

Model-exposure persistence occurs after full edit validation and before annotation
replacement. Manual, unseeded edits skip exposure scanning entirely. Imported
history survives pixel-identical reencoding and transfer, but this unsigned record
is not an attestation against deliberate external file modification.

Contracts and regression tests cover malformed geometry, raw Unicode and duplicates,
draft/review separation, omitted fields, retained seed history, revision conflicts,
COCO/snapshot/archive preservation, stale image hashes, evaluation invalidation,
reserved-acceptance privacy through MCP, and native canvas gestures. The [actual native walkthrough](../artifacts/text-region-authoring/native-ui.json) and [packaged runtime](../artifacts/text-region-authoring/bundle-verification.json) evidence are recorded separately from these software checks.
