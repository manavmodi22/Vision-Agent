# Duplicate probe audit

Read-only audit, 2026-10-29. No model inference, production edits or modification of captured runs. The current swapped-layout run was left untouched.

Current audited source: `a900515d20cb83d6a490e8f35c6389e284388e8ef4607d9e56c9c67b38252bd3`.

**Finding: transport/reservation idempotency is implemented; the cross-decision `no_new_information` policy promised by `docs/a0-implementation-plan.md:136` is absent.** Repetition counts and a system instruction are advisory. This is a policy gap, not a failure of the existing same-call dispatch lock.

## Exact captured comparison

Source: `.visionapp/a0-investigation/run-20261029T200305Z/report.json`, SHA256 `eb25a9c546e3f531de72b4d7d502418ec6fe2d69d45283e89dfdc8af0ec2843e`. Its runtime source before/after is `eccdf45df253baccdd3bc3a73f56b1746865b5f95823629664cd3cf5b5c49801`.

| | Action 7 | Action 12 |
| --- | --- | --- |
| Action ID | `4ee13bfb06db4fcd9ae23123c9afdd10` | `ac79697ea0534486a14cf0cb03efda72` |
| Model-call ID | `b02d85b27d24456b9cfc2328863c6ee7` | `f684fb83a715414cb27e59ddfaadd1b7` |
| Observation ID | `a6489127564649579814e6341e9d1036` | `822cfccba67743e6ac7b19c0fbab9cc7` |
| Actual execution | `executed=true`, `completed` | `executed=true`, `completed` |
| Total probe time | 380.527 ms | 360.342 ms |

Both typed action objects are exactly equal: `run_probe`, `model.apple-vision`, the same inspected descriptor hash, media ID, source PNG SHA256, no transforms, and OCR request `{task: ocr, model_id: apple-vision, languages: [en-US]}`. Their existing canonical argument hash is `6138cb60f9ceb2e3f7edd50129073e28fe1d9ffb1bc0130abe95f33960aff635`.

Both have identical 1600×500 adapter input, pixel hash `1a29cadc185239d3510ec7b95f6a236824849c9b2b844de27e474d0cb88557c3`, execution identity `e63ee72fbd4782bea414d6f693e3c2974859c52ec990659fb012753a266223b0` and configuration hash `81c8e6ffbf514841279646415e3eb3c651f68c976fee4df4c22617b3f14254c1`. Both return `ITEM CODE`, `QZ-4817`, `SHIP TO`, `IGNORE-552` with equal readings/geometry/confidence and warnings. The complete saved `InferenceResult` objects differ **only in timing**. Their immutable result artifacts were read and their SHA256 references verified.

Differences outside the execution arguments are legitimate record differences: distinct model calls, revisions, UUIDs, prose and provenance. Action 7 cites two observations; action 12 has `based_on_observation_ids=[]` and says it is confirming the full image to guide cropping. These differences do not change pixels, adapter settings or the probe computation. `RunProbe` has no explicit retest contract, so the prose cannot distinguish a requested repeatability measurement from an accidental repetition.

At call 12, action 7 was outside `recent_actions`' last-four window and its observation was outside current visible observations, although its ID remained historically citable. The repeat count is computed over the whole task but displayed only for recent action rows. This weakens visibility before the repeat; it is not a host duplicate guard.

## Current policy and tests

- `engine/investigations/store.py:178–233` permits one action per captured model call and enforces revision, exposure, stage and cumulative budgets. A new captured call can reserve identical arguments. `ActionReceipt` stores the typed decision but no persisted canonical argument digest (`spec/investigation.py:234–245`).
- `mcp_server/investigations.py:183–204` holds a cross-process dispatch lock and reuses an already completed receipt only when the **same latest model-call ID and complete decision** recur. Otherwise it reserves and runs the worker. This correctly protects a retried transport request, not later planner repetition.
- `engine/investigations/tools.py:326–353` checks current source/capability authority; `probes.py:130–174` executes and persists fresh results. There is no matching-prior-result lookup or `no_new_information` transition.
- `agent/investigation.py` says not to repeat unchanged actions. `mcp_server/investigations.py:71–92` reports canonical argument counts; its metadata deduplication affects prompt projection only.
- Existing tests cover reservation/completion idempotency (`tests/test_investigation_store.py:85`), concurrent same-call dispatch (`test_investigation_loop.py:346`), interrupted effects/no automatic execution (`test_investigation_store.py:177`), and repeated-context counts (`test_investigation_context.py:66`). None tests identical probes from **different completed model calls**, a one-time no-information receipt, or the subsequent inconclusive stop. Tests were inspected, not rerun during the live trace.

## Smallest domain-general correction to implement later

1. Keep the existing transport guard. Add task-scoped duplicate detection for successful probes across model calls, after current ownership/source/acceptance/capability checks and before another adapter invocation. Bind a persisted execution key to media identity/source hash, ordered transforms or transformed pixel hash, full typed request, and current resolved adapter/model identity. Do not count UUIDs, rationale, context revision, timestamps or artifact paths as new inputs. Changed actual input/model configuration must remain a new experiment.
2. For an ordinary repeated successful request, reserve and complete a transparent `no_new_information` receipt linking the original observation and its verified immutable artifacts, with `executed=false`. Expose the prior saved values or a correctly scoped retrieval pointer. Do not manufacture a fresh inference result. Persist the warning per execution key; another unqualified repetition ends inconclusive as the plan specifies, without selecting an alternative strategy. Keep action/attempt accounting honest and never label a skipped call an adapter execution.
3. Preserve intentional retesting explicitly. A small optional typed retest request should reference the prior observation and state the measurement reason; validate ownership and apply a bounded allowance using the existing probe budget. A new UUID or changed prose alone is insufficient. This makes deterministic receipt reuse distinct from deliberately measuring repeatability or timing. Do not reuse failed/interrupted/unknown outcomes as successful evidence, and do not apply a static-result cache blindly to discovery or media inventory that may have changed.

Required regressions: identical probes from different model calls reuse once then stop without a second adapter call; completed-receipt reuse persists across resume; changed pixels/media/model identity/request/transforms execute; revoked authority or reserved acceptance is still rejected before reuse; explicit bounded retests execute; failed/unknown attempts retain current reconciliation behavior; semantic result comparison excludes timing/record IDs but preserves literal values, geometry, identity and warnings. Keep original same-call concurrency tests.

This proposal does not claim that identical stochastic requests must produce identical results. It defines an explicit default reuse policy with a retest escape hatch; the captured Apple Vision pair supplies direct evidence of an actual redundant result in this run.
