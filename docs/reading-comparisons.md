# Reading comparisons and event output

A text comparison is a visible observation, independent from creating a local
stored event. Previously, any authored expected text retained a `sink_event`, so
"compare against ABC-990 exactly; do not create events" still generated events.
Removing that sink alone also hid the comparison result from the preview.

## Interface and ownership

`TextComparison` contains `block_id`, literal `expected`, ordered raw `observed`
strings, `mode` (`exact` or `contains`) and `matched`. Each executed `match` block
adds one record to `FrameResult.comparisons`, defaulting to an empty list for
historical results. Observations are captured before match-event filtering, so
both passes and failures remain inspectable. They do not write an event, grant
alert authority, normalize text, or change image-level evaluation metrics.
The runtime computes comparison semantics once and uses the same result for the
observation and the existing event-filter decision.

Fresh pattern decisions must state `record_events` explicitly. Reading candidates
with a comparison and `record_events=false` keep the match block and omit the
sink. Explicit event requests require `record_events=true`; absent or disabled
event requests require false. Detection candidates retain their count condition
and must agree with that same explicit event policy. A null value is reserved for
historical decisions and retains their old compilation semantics for replay.
Existing saved pipeline specs are never silently rewritten.

Adding or changing expected text through a parameter refinement preserves the
candidate's existing event sinks. Adding a comparison to a read-only graph does
not introduce a new sink. Structural event changes require their own supported
explicit action; changing a literal is not such an action. The refinement intent
validator rejects a literal-only patch that would silently omit requested event
creation, removal or filter changes and asks for clarification. Quoted comparison
values are treated as data even when they contain event-like instructions; an
apostrophe inside a double-quoted value does not end that value.

## Validation

Tests execute matching, mismatching and empty readings with and without sinks and
with each match-event filter; compare observations must stay present while event
output follows only the connected sinks. Literal Unicode/whitespace, multiple
comparison blocks, legacy result decoding and historical decision replay are
covered. Initial-request tests cover disabled, absent, required and contradictory
event policies. Refinement tests verify no invented sink and retained existing
sink behavior. Native decoding/presentation is validated separately.
