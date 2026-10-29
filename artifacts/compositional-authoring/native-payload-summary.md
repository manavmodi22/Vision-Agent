# Native release payload checks

Existing release binary decoded three actual backend frames and three saved plans. **263 checks passed**: 257 baseline checks plus six external payload decodes.

| Payload | Observed comparison | Saved reader bindings | Events |
|---|---|---|---|
| Initial crop/resize/OCR | `ABC-990` → exact match, true | `o` → Apple Vision | 0 |
| Parallel OCR and barcode | No comparison requested | `ocr_reader`, `barcode_reader` → Apple Vision | 0 |
| Right-half crop refinement | `WRONG-111` versus `ABC-990` → exact match, false | `o` → same Apple Vision binding and options snapshot | 0 |

The refined payload records a 900×300 inference input and `[0.5, 0, 0.5, 1]` input-to-frame transform. The original input was 1200×400 with `[0, 0, 0.5, 1]`.

The source `refinement-report.json` still records `passed: false` for `actual_new_pixels_and_false_comparison`. That verdict is preserved; successful Swift DTO decoding does not override it. No new inference, rendered UI verification, or model accuracy measurement is claimed.

See `native-payload-receipt.json` for source paths, JSON pointers, SHA-256 hashes, exact command arguments, typed-decode output, and observed values.
