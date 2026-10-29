# Evidence-context live run: preserved failure

This is actual local Qwen3.5-9B planning and Apple Vision inference on a generated
software fixture, not a successful app or A0 acceptance result. The run took
497.85 seconds and ended `inconclusive` after eight model calls, seven reserved
actions and two actual probes. No workflow preview or selected draft was created.

`report.json` and `task.json` are byte-for-byte copies of the completed run.
`snapshot.json` is the report's state/actions/observations member serialized as a
separate file. `manifest.json` records source paths, byte counts and SHA256 hashes.
The fixture and all task-owned tool artifacts are retained. Calls 7 and 8 include
exact captured prompts, schemas, responses and generated decisions under
`model-calls/`. Their model-call statuses are **completed**, not failed: downstream
workflow/action validation failed. `diagnosis.json` retains this distinction and
the full action timeline.

The run's source identity was
`b787a9d409db6f865b20915e5ba5e3202926a1144d21a6b8451726f7366373b3`, unchanged during
execution. `code-reference-snapshot/` contains selected source files as read during
this later audit, at identity
`4cdb873457ff1c5a5f1bad3dd9130078a32036dbc5a82ad68cabba08c55b503a`. It is a partial
audit reference, not a claim to be the original complete source tree. The captured
model-call prompts/schemas are authoritative for what the model received.

## What actually happened

1. The planner discovered capabilities, inspected Apple Vision and media metadata,
   then tried barcode reading. That actual probe completed with zero readings.
2. It changed its next experiment to OCR. Actual OCR returned `ITEM CODE`,
   `QZ-4817`, `SHIP TO` and `IGNORE-552`, with boxes and confidence values. All four
   readings were present in the model-visible workflow context.
3. It requested workflow construction, incorrectly asserting that OCR ignored the
   shipping label. Extraction confidence is not evidence of exclusion; the two
   shipping-label readings were still present. No crop, selective filter or other
   isolation experiment had run.
4. Call 7 produced OCR and event-sink nodes but omitted `frame_sample`. The graph
   DTO/JSON grammar accepted the shape; effect-free topology validation rejected
   it with `A composed candidate needs exactly one frame_sample source` before
   compilation or preview. The failed action observation was saved and exposed.
5. Call 8 attempted `prepare_workflow` again, but corrupted its citation. Actual
   visible ID: `3f9f351e92c0480b97976ee4b44b7435`; generated ID:
   `3f9f351e92c0480b97976ee44b743508`. Both match the 32-hex syntax, but only the
   first exists. The store rejected the action before reservation. The outer loop
   converted that tool error into terminal `inconclusive`; no further repair turn
   occurred despite remaining budget.

The workflow call also re-received the model's unsupported exclusion claim in
`prepare_workflow.payload.selected_action.summary` and in
`recent_actions[].arguments.summary`. Removing earlier `purpose` prose did not
remove this model-authored claim. It remains a possible reinforcing influence,
separate from missing graph contract semantics. A current-contract replay must
retain these historical summaries unless an additional explicitly labelled
experiment is authorized; silently cleaning them would confound the comparison.

## Workflow support and remaining structural errors

The captured workflow schema did include `SampleNode`, with `type` first and
required `type`, `id`, `fps`. This was not the earlier discriminator-order bug.
The system prompt said references are `$node_id.port` and that `frame_sample`
owns the host-bound source. The node docs showed output port types, but did not
explicitly expose the exactly-one-source invariant or required input-port types.
The graph's flat array grammar does not enforce topology.

Two further errors are statically present in the same proposed graph. They were
not reached during the actual failed construction because the missing source was
rejected first:

- OCR references `$media-0e53fc77549b0b5080d45aedd9373425.png`, but this is not a
  node or image-producing output port. Media selection belongs in `media_ids`;
  the host binds it through the source node.
- `sink_event.event` references `$ocr-reader.text`. That port produces text, while
  the sink requires an event. Plain reader output needs no event sink. An event
  should only be added when the requested behavior needs one and a valid event
  producer exists.

Call 7 had 7,828 input tokens and a 2,600-token output allowance within the verified
16,384-token context. It ended normally, so truncation/context exhaustion does not
explain this graph failure.

## Small general changes indicated by this trace

These are recommendations from the preserved trace; concurrent root work may
already implement parts of them. They do not prescribe OCR, a fixture crop, a
success label, or a fixed experiment sequence.

- Expose graph invariants and input/output port types in the workflow contract:
  exactly one source, references only to existing compatible node ports, selected
  media bound by the host, and optional event sinks. Keep deterministic validation
  authoritative; never silently repair an emitted graph.
- Ground ID-valued output fields in the exact host-authorized observation set, or
  validate them before recording a decision as executable. Return bounded,
  persisted feedback for pre-effect reference/topology errors and allow the model
  to repair within its existing cumulative budget. Unknown-effect failures and
  cancellations must still stop; never guess or substitute the intended ID.
- Make the general obligation to test exclusion/selection constraints explicit.
  The model should use actual readings and geometry to choose and verify its next
  hypothesis. A correct string among distractors does not satisfy “only”; neither
  confidence nor a successful tool status establishes task correctness. Preserve
  draft readiness separately from quality acceptance.

No production files or tests were changed for this audit. No inference, action
dispatch, server change, approval, review, candidate overwrite or commit was made.
