# Paired workflow-call diagnostic: 9B and 14B

Both models received the same captured workflow point, with current contracts at
source `983d70a78951ed22652055fe2a9cae449dafdfa6548fca3cf7081c733e3fb62f`.
Comparison of both planned and actual wire-request JSON proves that **only the
`model` field differed**: system/user messages, output schema, temperature 0 and
2,600-token output allowance were identical. Backends/ports, model weights,
tokenizers/templates and cache state naturally differed. This is not a controlled
speed benchmark or an A0 acceptance run.

| Candidate | Generated graph | Additional issue | Actual execution |
| --- | --- | --- | --- |
| Qwen3.5-9B | frame_sample → full-image Apple Vision OCR | Claimed shipping-label exclusion without an isolation operation | Manual diagnostic returned ITEM CODE, QZ-4817, SHIP TO, IGNORE-552; exact reference check failed |
| Qwen3-14B | frame_sample → full-image Apple Vision OCR | parent_revision_id was the task ID, although no workflow revision existed | Not executed |

Both graphs passed structural checks. The raw graphs and exact model-generated
output text are preserved here; full original requests/responses remain in the
adjacent model-specific directories, hashed by `input-manifest.json`. The original
candidate validations are preserved unchanged. Their limited validation did not
yet check parent workflow ownership; `summary.json` separately records why the
14B parent is invalid under the existing host authority and new grounding check.

The 9B manual preview is separately recorded under
`../workflow-call7-current-qwen35-20261029/manual-preview/actual-preview/`. It ran the
exact generated graph on copied fixture bytes, through actual Apple Vision, with
no fabricated investigation authority or changes to the original task. No result
was fed back into either captured diagnostic.

The 9B receipt reports 105.10 seconds; the 14B receipt reports 146.58 seconds. The
14B backend timing fields separately report 164.83 seconds of prompt processing
and 59.66 seconds of generation, inconsistent with that receipt elapsed value.
These raw observations are retained, without deriving relative performance.

Both requests retained the earlier model-authored false exclusion claim in the
prepare-workflow summary. Later projection omission and workflow-revision
constraints are subsequent changes, not part of this pair. Neither candidate
establishes a useful app, a preferred planner, or success at the requested task.
No additional inference was performed to assemble this comparison.
