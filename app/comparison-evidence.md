# Native comparison evidence

The preview displays executed text-comparison observations independently of local
event output. A comparison can therefore show a match or mismatch without creating
an event, and a filtered event does not hide the comparison that produced it.

`FrameResult.comparisons` is an optional array for historical decoding. Each
`TextComparison` carries `block_id`, the raw `expected` string, raw `observed`
strings, `mode` (`exact` or `contains`), and the engine's `matched` Boolean. Swift
does not recompute the match, normalize strings, infer a result from an event, or
turn a result into an accuracy or approval claim. A workflow with a match block
but no recorded comparison evidence displays an unavailable state. Existing
reader regions, workflow text, and event results remain separate.

The preview shows each comparison's block, mode, result, expected value and
observed values. Raw values are selectable, with Unicode code points available
to inspect lookalike characters. No expected value is substituted for a missing
observation. Empty observations are shown explicitly.

Model proposals gain an optional `block_id` in `PlanCandidateModelSelection`.
When present, both the compact build plan and its detail view identify the
specific inference block. Historical candidate-level selections retain their
existing labels and decoding behavior.

Validation covers legacy and current frame decoding, comparison output with zero
events, raw Unicode/whitespace round trips, empty observations, missing evidence,
and per-block model labels without leaking selections between candidates. Native
checks establish the wire and presentation contract; an installed-app walkthrough
with actual inference is separate acceptance evidence.
