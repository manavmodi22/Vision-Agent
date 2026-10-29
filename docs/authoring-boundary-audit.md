# Authoring boundary audit · 2026-10-28

Scope: image import followed by COCO annotation import, portable dataset versions,
and concurrent edits to an existing pipeline. Read-only review of implementation
changes; verification used isolated temporary projects and the dataset tests.

## Findings resolved

1. **COCO labels previously attached to a duplicate image.** The media importer
   normalizes filenames and image format, so original COCO names did not match
   imported images. The fix records source provenance and uses normalized pixel
   identity for legacy imports. Ambiguous matches are rejected, and EXIF-oriented
   annotations require explicit normalization. Re-running the original failure
   now keeps one image and attaches its annotation to the existing image path.

2. **A version's hash previously described the live dataset, not its portable
   snapshot.** The snapshot now hashes rewritten relative annotation paths and
   copied images, retaining `source_dataset_hash` separately. Recomputing both
   hashes from their respective datasets matches the saved values. Snapshot
   manifest and COCO paths are portable as well.

3. **Stale pipeline edits previously overwrote newer edits.** Candidate PUT now
   requires `base_spec`; the service compares it with the current candidate under
   the workspace lock and returns a conflict before saving a stale edit. Native
   request serialization includes the original baseline. Existing evaluation and
   deployment evidence remains invalidated when a real edit succeeds.

Verification: the original COCO and snapshot failure reproductions pass after the
fixes; all 10 dataset tests pass, including ambiguity and stale-edit checks.
No additional actionable issue was identified in this narrow review. This is not
a general assessment of model accuracy or production readiness.
