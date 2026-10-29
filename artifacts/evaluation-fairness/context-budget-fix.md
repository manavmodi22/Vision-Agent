# Warehouse prompt-budget regression

Replayed the exact recorded inputs from project `686fdd7449f44b0e` and operation
`461421af47984338b3420cab81eeaff8`, retaining the real blocks list, dataset context,
installed model-options snapshot, authoring/detection/alerting playbooks and output
schema. No model client was constructed and no tool effects were reexecuted.

| Render | System and playbooks | User and context | Output schema | Total / 24,000 |
|---|---:|---:|---:|---:|
| Original exact 194-character goal | 13,271 | 8,430 | 2,369 | 24,070 — rejected |
| Compact experimental entries, same goal | 13,271 | 5,862 | 2,369 | 21,502 — accepted |
| Compact entries, 1,318-character normal goal | 13,271 | 6,986 | 2,369 | 22,626 — accepted |
| Same long goal, simulated 100 experimental models | 13,271 | 7,397 | 2,369 | 23,037 — accepted |

The only runtime change is the experimental-model projection in
`agent/model_selection.py`: at most eight noneligible entries contain capability
ID, declared purpose and reason. A summary gives total/shown/omitted counts and
purpose counts. Eligible options retain their planning facts, including an
explicitly requested experimental model. Full provenance remains unchanged in the
captured options artifact. The context limit and required guidance are unchanged.

Complete rendered inputs are saved in `context-budget-before.json`,
`context-budget-after.json`, `context-budget-after-long.json` and
`context-budget-after-100-models.json`. The portable regression fixture is
`tests/fixtures/planner-context-warehouse.json`. The 100-model case expands the
captured shape in memory; it does not install or register models.

Validation: 54 prompt-budget/provenance/selection checks passed; strict mypy on the
two planning modules and scoped Ruff passed. This establishes pre-LLM budget
behavior, not live model comprehension or model-selection quality. Very large
eligible catalogs or other project context still face the same hard budget guard;
this change specifically bounds the experimental inventory's prompt cost.
