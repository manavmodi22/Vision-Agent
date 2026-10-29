# Native reading evidence

The original `VisionApp --analyze-image IMAGE` response remains exactly
`{"texts": [...], "barcodes": [...]}`. The engine opts into rich evidence with
`--analyze-image IMAGE --protocol 2`. Unknown versions fail on stderr with status 2;
they never open the app or silently fall back. Both versions retain strict single
JSON stdout ownership through process exit.

Protocol 2 carries `schema_version`, `request_policy`, `coordinate_space`,
`input_size`, the two legacy projections, `readings` and `warnings`. Reading rows
have raw `text`, `kind`, nullable normalized top-left `box`/`polygon`, nullable
`confidence` and nullable `symbology`. The image's EXIF orientation is applied by
Vision; reported dimensions describe the oriented input. The unchanged accurate,
en-US-only, no-language-correction request policy is `apple-vision-en-us-v2`;
output protocol and bridge content hash are separate execution identity inputs.

OCR confidence comes from the actual recognized candidate. Barcode confidence
stays null: the generic observation confidence may be an unsupported sentinel.
Quadrilaterals come from actual observations. Boxes are their envelopes. Invalid,
degenerate or out-of-frame geometry is omitted with a bounded warning; raw text
is retained. No full-image geometry, confidence or expected strings are invented.
Output is limited to 10,000 readings, 16,384 Unicode scalars per value, 1 MiB of text
and 20 warnings, matching the shared adapter contract.

Preview decodes `FrameResult.inferences`, applies each block's `input_to_frame`
once, and draws cyan reading regions separately from object detections. Selecting
a numbered row or preview region shows raw text and optional Unicode code points.
The reader's actual model, adapter, provider, timing and execution identity are
inspectable. Missing historical geometry stays unavailable. Same-basename images
in different directories cannot borrow each other's predictions.
The separate workflow text projection remains visible alongside reader evidence,
so OCR plus visual-judgement graphs retain both actual outputs. Missing reader
regions are described as unavailable; current judgement output is not labelled
legacy merely because it has no OCR inference record.

Contextual review now supports separate editable text regions and object boxes.
Reading workflows default to text regions. Prediction regions remain read-only;
explicit copying creates unreviewed labels with the original observation and
execution provenance retained. Manual image-level expected text stays compatible;
an explicit review sheet can instead link those values to region transcripts.
Opening a preview or review performs no inference and never marks an image reviewed.
Text accuracy, CER and WER remain image-level metrics, not spatial OCR or
reading-order quality. See [text-region editing](text-region-editor.md).

The preview separately displays typed `FrameResult.comparisons` observations:
comparison block, exact/contains mode, raw expected and observed values, and the
engine's match result. A comparison remains visible with zero emitted events.
Historical comparison previews without those observations show unavailable
evidence; the app does not reconstruct a match from an event or recompute literal
Unicode equality. Pass/fail describes the comparison, not measured reader
accuracy. See [comparison evidence](comparison-evidence.md).

Checks cover geometry conversion/envelopes, crop mapping, missing confidence,
duplicate text IDs, Unicode distinction, legacy decoding, strict stdout and review
provenance. `artifacts/native-reading-v2/probe.py` records bounded real Apple Vision
outputs and overlays for existing exact/substring/pallet fixtures plus generated
EXIF-rotated/mirrored, skewed and QR inputs. These prove protocol and coordinate
behavior on those inputs, not general reading quality. Native UI acceptance remains
a separate test by the root agent.

API references: [recognized text](https://developer.apple.com/documentation/vision/vnrecognizedtext),
[rectangle observations](https://developer.apple.com/documentation/vision/vnrectangleobservation),
[normalized lower-left boxes](https://developer.apple.com/documentation/vision/vndetectedobjectobservation/boundingbox),
[barcode observations](https://developer.apple.com/documentation/vision/vnbarcodeobservation),
[generic observation confidence](https://developer.apple.com/documentation/vision/vnobservation/confidence).
