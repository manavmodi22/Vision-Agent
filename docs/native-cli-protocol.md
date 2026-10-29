# Native OCR CLI output ownership

The OCR CLI reserves the caller's original stdout descriptor for one encoded
`{"texts":[],"barcodes":[]}` response and newline. Before invoking Vision, it
redirects process stdout to stderr, including buffered C stdio and exit-time
diagnostics. The reserved response descriptor is close-on-exec and is never
restored to process stdout. Failures emit diagnostics on stderr and return nonzero.
OCR policy, text values, barcode behavior and the legacy JSON fields are unchanged.

The initial packaged relocation failure reported extra data after JSON. Its exact
diagnostic was not captured. Six unmodified reproductions using the same
1000×300 Arial64 PALLET/DOCK image, with spaces in the temporary working directory
and image path, all returned strict JSON and empty stderr. The relocation retry
also passed. This is protocol hardening, not a claim that a specific framework
message was reproduced or identified.

`artifacts/native-ocr-stdout-investigation/report.json` preserves pre-change raw
stdout/stderr and binary/image hashes. Native subprocess checks deliberately
write immediate and exit-time C stdout diagnostics, then verify that the response
pipe contains exactly one JSON document. A failing child must produce no JSON,
stderr diagnostics and nonzero status. Actual OCR probes are reported separately
in `artifacts/native-ocr-stdout-validation.json`; strict parsing remains enabled.
