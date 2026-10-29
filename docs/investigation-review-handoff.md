# Importing an investigated draft for review

The human-facing handoff connects an investigation's saved workflow to the existing application candidate, annotation, evaluation and approved-run path. It does not call a planner or confer deployment approval.

Eligible tasks are terminal `draft_ready` or `inconclusive`, with a current selected immutable workflow and a matching successful actual preview. The first implementation requires an empty application, no prior build, and no active investigation work. Inconclusive recovery is explicit: the proposal and durable build origin retain the original task status and stop reason. The investigation ledger is never rewritten to claim completion.

## Protocol

All endpoints are under `/projects/{project_id}/investigations/{task_id}/handoff`; none are registered as MCP tools.

- `POST /prepare`: `expected_revision`, `workflow_revision_id`, `preview_observation_id`. Returns a hashed proposal showing the original and new source binding, original/new spec hashes, example counts, proposed metric/target, and limitations. No inference occurs here.
- `POST /accept`: `proposal_id`, `proposal_hash`, `client_request_id`, `acknowledge_source_rebind: true`. Durably reserves the operation, performs a real preview on up to five project development images, then commits one candidate and a paused review build. Returns `{receipt, build}`; `build.investigation_origin` is the same receipt.
- `GET` the base path: returns the durable status, proposal, completed receipt and current matching build. After process death it may finish already-captured document writes, but never repeats uncertain inference. A later unrelated build is not returned as this handoff's build.
- `POST /abort`: `proposal_id`, `proposal_hash`, `acknowledge_discard: true`. Explicitly discards an incomplete commit when current project/build documents still belong exactly to it. Original investigation, preview, plan and receipt evidence remain. External media changes are not reverted. A completed import cannot be discarded through this endpoint.

Public statuses are `none`, `prepared`, `committing`, `completed`, `interrupted`, and `conflict`. A conflict may set `can_abort: true`; the user can restore exact evidence and refresh, or explicitly discard the incomplete import. Foreign project/build edits are never overwritten. After a safely interrupted/discarded operation, a fresh prepare is an explicit new attempt.

## What changes and what stays bound

Investigation specs refer to frozen selected-sample folders. Existing app candidates require the imported project `media` folder. Accept changes only that source field: block IDs, order, input references, parameters, frozen zone paths, declared model IDs and per-block bindings remain exact. The new candidate gets its own spec hash and actual preview; the earlier selected-sample preview is retained as its origin, not relabeled as new execution.

The backend verifies content-addressed artifacts, revision/action/observation ownership, the original source and pixel hashes, frozen media, captured model options/descriptors, zone dependencies and actual inference identities. It rechecks the project and relevant input fingerprints before commit. Unrelated planner settings do not alter an already-typed CV graph; actual model/adapter drift still rejects it.

Apple Vision identity includes the native bridge executable's bytes. A new UI binary is therefore not equivalent to a previously used bridge. An explicitly configured, verified original bridge can preserve the actual runtime; a changed bridge must not be presented as the same identity. This handoff does not implement runtime migration or silently accept a new model implementation.

The application opens at the existing evidence review checkpoint. Imported labels, reviewed flags, fixture/synthetic provenance, source groups and acceptance reservations are preserved. The new preview excludes reserved acceptance images and records development exposure. It writes no evaluation result, deployment, recorded event or external alert. Existing reviewed-data requirements, independent-acceptance rules and explicit local-trial/deployment approval remain enforced. A single correct preview is a usable saved candidate, not measured quality or permission for recorded operation.

## Persistence and failure behavior

A project journal records the proposal and pre-effect preview reservation. An ownerless preview is marked interrupted; retrying its accept does not run it again. Once the actual result and intended project state are durable, recovery writes the exact candidate, build, platform plan and receipt idempotently. Crashes between plan/execution-binding writes recover the same plan rather than fabricate new tool calls.

Incomplete commits block build continuation, evaluation, deployment and ordinary API-owned project mutations until recovery/discard. Preview-time edits may proceed but invalidate the pending import through CAS. Discard uses its own recoverable reservation and restores only the exact handoff-owned project document; it cannot overwrite unrelated edits or delete another build. Immutable evidence remains for audit.

Protocol tests use real execution of the explicitly synthetic fixture adapter and generated images. They cover HTTP DTOs, non-source graph/model preservation, unreviewed labels, six commit crash points, uncertain preview non-repetition, stale/tampered evidence, safe conflict/discard, acceptance exclusion, binding inheritance through refinement, and concurrent accept. These tests are not learned-planner acceptance or production accuracy evidence.
