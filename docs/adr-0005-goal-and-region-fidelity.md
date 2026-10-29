# Initial goal and region fidelity

Owner: application integration. The main entry point creates a custom project;
its planner must support the same pallet, damage and reading tasks as the reference
flows without asking the user to choose an implementation preset.

New real projects start with no spatial geometry. A lane name does not establish
a polygon. Region geometry is confirmed only by a human save, bound to the exact
zone-file hash, or by the explicitly generated geometric fixture. Legacy geometry
without that provenance stays visible as unconfirmed and cannot silently become
the agent's known warehouse layout.

The planner decision adds `use_zones` and optional `zone_ids`. The engine context
supplies only confirmed names. A region-dependent decision with unavailable names
returns `needs_zones`, and the native build opens a contextual drawing step. Save
and continue replans the same original goal. ZoneFilterParams.include_ids selects
named regions from the live saved file; unknown names fail compilation. Changes
to geometry continue to invalidate evaluation and deployment evidence.

Pure counting produces counts without inventing a capacity or event rule. Pure
OCR/barcode reading does not require a global expected SKU; comparison tasks still
need the requested expected value. The planner, compiler and durable staged-result
checks must agree on these decisions. No state, score or label review is inferred
from model prose.

Validation covers empty and legacy regions, confirmed geometry changes, selected
region scope, custom entry-point task intent, clarification/resume and actual
local-model benchmarks. Synthetic geometry checks prove software behavior only.
