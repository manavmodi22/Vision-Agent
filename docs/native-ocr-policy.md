# Native OCR request policy

`apple-vision-en-us-v2` uses one `VNRecognizeTextRequest` configured with accurate
recognition, `recognitionLanguages = ["en-US"]`, automatic language detection off,
and language correction off. The compiler currently accepts only English reading
requests. Barcode detection and the `--analyze-image` JSON shape are unchanged.
Apple documents the language selection and automatic detection properties in its
[text recognition request reference](https://developer.apple.com/documentation/vision/vnrecognizetextrequest).

Native checks inspect the request actually used by the bridge and verify that
its revision supports `en-US`. The engine binds the policy version, bridge binary
hash, and OS identity into reading evaluation provenance; changing the request
cannot silently reuse older reading scores.

## Observed limitation on the existing acceptance images

On macOS 26.7.1, the baseline and explicit-English request both read the exact
image as `ABC-990`. Both read the substring image as `ХABC-990Y`, whose first
character is Cyrillic U+0425, although the fixture was rendered with Latin X
U+0058. Explicit language configuration therefore **does not fix this observed
confusion**. Raw strings are retained; no Unicode substitution, normalization, or
LLM correction was added. These two probes do not estimate general OCR accuracy.

`artifacts/native-ocr-language-policy-baseline.json` records the prior binary,
image hashes, outputs, Unicode codepoints and timing. The corresponding updated
release probe is `artifacts/native-ocr-language-policy.json`. Native platform
validation remains separate from this actual OCR observation.

## Geometry protocol 2

Fresh engine reads now explicitly call `--analyze-image IMAGE --protocol 2`.
The native bridge reports its request policy, input dimensions, raw text/barcode
observations, and normalized top-left quadrilaterals with their bounding envelopes.
OCR confidence is the actual recognized-text candidate score; barcode confidence
remains unspecified. Invalid geometry is omitted with a warning instead of clamped
into an invented region. Duplicate observations and Unicode codepoints are retained.

The engine validates protocol/policy, dimensions, coordinate space, observation
bounds and text projections before execution evidence is accepted. The output
protocol, binary content and system identity bind the result. An old bridge cannot
silently supply a string-only fresh result. The original three-argument CLI still
returns its original string-only payload, and historical evidence remains readable.

Native preview renders reading geometry separately from object detections and maps
adapter crop/resize coordinates to the original frame once. Expected-text corrections
remain annotation ground truth, separate from model observations; reviewing a
transcript does not certify the model's polygons or establish field-level accuracy.
