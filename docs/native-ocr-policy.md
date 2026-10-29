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
