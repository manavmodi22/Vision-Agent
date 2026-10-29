+++
format = "visionapp.skill.v1"
id = "reading"
title = "OCR, barcode and field comparison"
task_types = ["reading"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Select for reading text/barcodes, printed fields, SKU checks or the labels use case."
required_inputs = ["Representative label or barcode images","Exact literal only when comparison is requested","Matching and event semantics"]
allowed_tools = ["blocks_list","block_schema","dataset_context","pipeline_validate","pipeline_run","eval_create","eval_run","build_context","build_prepare_review","review_queue"]
output_artifacts = ["Reading pipeline","Recognized text with source image","Field comparison evaluation"]
validation_recipe = ["Score reviewed expected text with declared normalization","Preserve exact versus substring matching and event polarity","Report measured CER/WER, exact text-list accuracy and recognition failures"]
failure_modes = ["Missing comparison value","Leading zeros lost","Exact/contains confusion","Unsupported language or unreadable text"]
version = "1.0.0"
+++

# Read the requested fields
Use an implemented OCR or barcode adapter appropriate to the media. Reading-only requests do not need an expected SKU. When comparing, copy the supplied literal exactly, including case and leading zeros. A generic reference to "the expected SKU" is not itself the expected value.

The model must explicitly state match_mode and match_emit. Exact equality uses exact; substring search uses contains. Emit matched for events only on a match, mismatched for only failed comparisons, and all for ordinary check-whether output. Do not add an object detector or spatial count rule to a reading-only pipeline.

Benchmark OCR candidates on the project's text, language, lighting and scale. Keep raw recognition separate from field normalization. Report character/word error rates only when the evaluator returns them, with its saved normalization policy and counts. Exact text-list accuracy is not a named-field semantic score.

## Examples
- "Read package codes": return decoded text without a match block.
- "Create an event only when text exactly equals ABC-990": expected_text ABC-990, match_mode exact, match_emit matched.
- "Compare against the expected SKU": ask for its value; do not use the words expected SKU as the value unless explicitly quoted as a literal.
