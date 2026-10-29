# Native text-region editing

The contextual DatasetStudio uses one canvas with separate **Text regions** and
**Object boxes** label modes. Reading workflows default to text regions; a user's
explicit mode choice survives refreshes. Text rectangles require no object class.
Users can draw, select, move, edit four corner handles, delete, transcribe, undo,
redo, pan and zoom. Saved text labels use solid purple outlines. Reader predictions
use dashed cyan outlines and never become labels automatically.

The shared `Annotation.text_regions` contract stores stable IDs, four convex
normalized points in oriented full-frame RGB coordinates, their derived box,
nullable raw transcript and nullable compact seed provenance. The native editor
matches the server's convex-turn tolerance of 1e-8. Empty transcripts are drafts.
It preserves exact Unicode bytes, including canonical-equivalent representations;
it does not substitute lookalike characters or normalize recognized text.

Explicit **Copy selected prediction to unreviewed labels** accepts an actual OCR or barcode
observation with valid quadrilateral geometry. It applies `input_to_frame` once,
preserves the original input-space observation, model/adapter/identity, transform,
index and timestamp. It requires the preview's `source_image_sha256` to match the
imported file bytes at copy time; stale images are rejected and historical previews
without image identity require a new preview. Existing
seeds are retained when the user corrects text or geometry; they are not rewritten
on import/re-encoding. Exact-path/candidate checks happen before presenting the
copy action. No model runs when a page is opened or a prediction is copied.

Every region edit clears review, including undo/redo of label changes. The review
toggle is unavailable while autosave is dirty or saving; after edits persist,
the user's explicit review action is a separate write. Incomplete transcripts
cannot be marked reviewed. Existing revision/CAS conflict handling preserves the
draft and requires explicit discard/reload. Navigation and closing flush saves.

`expected_text_source` defaults to `manual` for historical annotations. Existing
image-level values are preserved when regions are drawn or copied. **Use region
transcripts for evaluation** shows current and proposed values before switching
to `regions`. The server and native projection preserve all non-null literal
transcripts in region-list order, including duplicates. Region mode displays the
projected values read-only; switching back to manual retains those current values.

Current workflow output deduplicates repeated text values; projected duplicates
can therefore fail the existing text metric. The editor explains this limitation.
Neither image-level text accuracy nor CER/WER measures polygon location, repeated
instance localization or reading order. No spatial OCR accuracy is claimed.

The grid reports object-box and text-region counts separately; the empty filter
requires both counts to be zero. **Export all labels** saves `.vision-labels.json`;
**Import all labels** requires matching already-imported images and explicit
replacement selection. The engine validates decoded image hashes. Imported labels
always need review in the destination project. The JSON contains no image bytes.
COCO actions are explicitly labelled object-box-only.

Native checks exercise actual offscreen AppKit mouse events for text drawing,
movement/corner editing and object-box drawing/movement/resizing, alongside
geometry validity, crop mapping, provenance, raw Unicode, duplicate projection,
store undo/redo, pending-review guards, historical decoding and CAS request keys.
The checks create temporary generated image pixels and do not open a window,
access the camera/screen, invoke a model or modify a user project. The [installed native walkthrough](../artifacts/text-region-authoring/native-ui.json) separately verifies visible prediction copying, transcript correction, undo/redo, autosave, native label roundtrip and main-canvas drawing/corner/move edits. Contextual-sheet dragging returned an automation window error; the same actions succeeded in the main Annotations view. No review or model-quality acceptance follows.
