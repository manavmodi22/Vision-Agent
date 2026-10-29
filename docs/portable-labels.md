# Portable label archive

Ownership: schema/backend/integration in root; independent review in agent_harness;
exposure ledger in vision_core; native import/export in native_app.

The contextual dataset editor exports all labels as a versioned JSON document.
Unlike COCO object-box export, this includes text quadrilaterals, exact transcripts,
the image-level text source policy, and original model-seed provenance. Image bytes
are separate: users import the matching images into the destination project first.

`GET /projects/{id}/dataset/export-labels` returns `LabelArchive` version `1`.
Each image has its filename, oriented RGB dimensions, source byte and decoded-pixel
SHA256, complete annotation, and known model-exposure reasons. Paths are reduced
to filenames; they never authorize file access on import. Coordinate space is
`normalized_top_left_oriented_rgb`. No score, split or deployment approval travels
with the labels.

`POST /projects/{id}/dataset/import-labels` takes a selected local JSON `path`,
`base_revision`, and `replace_existing` (default false). Import validates every
entry before saving, matches only already-imported images by decoded-pixel identity
and dimensions, rejects duplicate or ambiguous matches, and preserves all other
project images. Filenames alone cannot match an image. Existing labels need explicit
replacement. Imported labels always need human review in the destination project.
Missing fields that would erase modern annotation data are rejected by the shared
save boundary. Model seed and prior exposure history survive transfer and later
deletion; the archive is a provenance record, not proof of independence or a signed
attestation against external file edits.

The file is bounded to 32 MiB, 5,000 images and 200 classes. Unsupported versions,
invalid geometry, changed revisions, conflicting class names, missing images and
malformed hashes fail without changing labels. Import uses the normal save boundary
to invalidate evaluations, update exposure, and preserve optimistic concurrency.
No inference, acquisition of images, external delivery or approval is performed.

Validation covers round-trip text/geometry/Unicode/duplicates, exact pixel matching
across filenames and encodings, duplicate/missing image rejection, review reset,
revision conflict, replacement policy, retained non-imported rows, HTTP contracts,
and exposure propagation after a model-seeded region is deleted.
