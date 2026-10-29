# Initial reading comparison and event policy

Status: staged pending the frozen benchmark; not applied to the live runtime.

The existing `match` block compares either exact values or substrings, but initial
planning omitted its mode and always compiled the template default `contains`.
It also emitted a `label_check` event for both true and false comparisons, so an
initial request to create an event only on a match could not be faithfully built.

Add optional `emit: all | matched | mismatched` to `match` parameters. Its default
is `all`, preserving existing 0.1 graphs and stored comparison results. This is an
additive backward-compatible parameter; no block type, port, or storage policy
changes. `matched` emits only a true comparison; `mismatched` emits only a false
comparison. Other frame outputs, including read text, are unchanged. This policy
filters pipeline events, not the engine's approved-run evidence persistence.

Initial typed choices expose `match_mode` (default `contains`) and `match_emit`
(default `all`). Explicit equality/substring requests and conditional match or
mismatch events are validated before compilation. A plain “check whether” keeps
both results. Graph summaries describe conditional emission from actual params.
Unresolved references to the expected SKU or correct code require a question,
even if the model puts a placeholder into the choice. Explicit quoted literals
and supplied clarification values retain their exact contents. Numeric barcodes
remain strings with leading zeros; complete bare identifiers are accepted, while
generic placeholders stay unresolved unless quoted. The bounded parser never
accepts a URL or multiword value by truncating it to the first token; these need
a complete quoted literal. Invented comparison values absent from the brief or
clarification are rejected. Reader intent checks do not parse numeric codes as
object-count thresholds.

Runtime comparison tests cover both readers, both modes, all three policies, and
matching/nonmatching text. A separate actual Apple Vision OCR smoke reads two
generated text fixtures and verifies all three policies. These are software
semantics checks, not detector accuracy or deployment approval. Live planner
cases are separate from the previously frozen 25-case suite; historic results
must not be rescored or reported as a new perfect full-suite result.
