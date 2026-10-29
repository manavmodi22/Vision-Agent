# Investigation draft → application review: implementation proposal

Status: **proposal only; no handoff implemented or exercised by this audit**. Read-only source review on 2026-10-29 while the frozen swapped-layout investigation ran. No model calls, server changes, production edits, or new acceptance claim.

## Recommendation

Add a human-invoked, evidence-bound **Import draft for review** operation. It imports the selected saved workflow into the existing candidate/build review lifecycle, preserving the exact operator graph, parameters, model bindings, frozen geometry, original sample identities, and investigation provenance. It does not invoke the planner, approve deployment, or invent an evaluation result.

There is a real source-binding difference to expose: an investigation spec points at its immutable selected-sample directory; application candidates currently must point at the project's imported `media` directory. The smallest compatible handoff explicitly authorizes this rebind, produces a new candidate hash and actual bounded preview, and retains both source manifests. It must not present the old selected-sample preview as execution of the newly bound spec. A static crop remains the same static crop; importing it does not prove applicability to other layouts.

## Existing seams and constraints

| Source | Existing behavior / reuse |
|---|---|
| `engine/investigations/workflows.py:91` | Saves immutable proposal, exact compiled spec, planning options, block bindings, input references and actual preview; writes revision receipt at `:224`. Preview sources are copied into the task-owned revision folder. |
| `spec/investigation.py:164`; `engine/investigations/store.py:265` | Successful host preview evidence selects the revision and observation. Selection alone is not quality evidence. |
| `engine/service.py:105`; `engine/builds/refinement.py:38` | Both require app source `media`. `save_candidates` replaces all candidates and invalidates approvals; it is not a safe append/import primitive by itself. |
| `engine/runtime/__init__.py:16` | Compiles, excludes reserved acceptance paths, records development exposure, and executes bounded real previews. Reuse this for the rebound candidate; do not use the unrestricted project folder as an untracked inference input. |
| `engine/builds/store.py:47,115,153`; `engine/builds/manager.py:60,261` | Durable build fingerprints, review/continue states and reviewed-label checkpoints already exist. A dedicated adoption entry point can start here after planning, without `BuildManager.start()` or `_plan()`. |
| `engine/platform/store.py:126,149` | Immutable build plans capture planning options and per-block model selections; later refinement inherits only exact matching evidence. Import must populate these receipts explicitly. |
| `engine/agent_state.py:371` | `commit_plan` requires a genuine staged planning operation. Do not manufacture an operation or captured compiler/tool calls to reuse it. |
| `engine/service.py:241,329,368` | Evaluation, explicit deployment/local-trial approval and recorded-run gates are already separate. Keep them intact. `/review` is event review, not this draft handoff. |
| `app/Sources/VisionApp/InvestigationViews.swift:137` | The current dead end is explicit. `InvestigationDTOs.swift:121` validates selected preview presentation, but server-side artifact verification must remain authoritative. |
| `app/Sources/VisionApp/InvestigationWorkspaceStore.swift:9`; `BuildView.swift` | Runtime/session selection currently separates investigation and legacy build screens. A durable imported-build association is needed so relaunch follows the reviewed app while retaining investigation history. |

## Small backend/API slice

Implement one new handoff module and typed request/receipt, with two human-facing API operations under `/projects/{project_id}/investigations/{task_id}/handoff`. Do not expose them as agent tools.

1. **Prepare** creates an immutable, reviewable handoff proposal. Inputs: expected task revision, selected workflow revision, preview observation ID, and project-authoring fingerprint. Host reads and verifies the actual action/observation/revision/artifacts. It returns an opaque proposal ID/hash, exact before/after source binding, original media IDs/hashes, intended project media manifest, graph/model/geometry hashes, proposed evaluation metric/target, and replacement/invalidation impact. Preparation need not perform inference or mutate candidates.
2. **Accept** takes the proposal ID/hash plus a client idempotency key and explicit source-scope acknowledgment. Verify snapshots again, compile the saved spec with only `inputs.source` rebound to `media`, and run a bounded real development preview using the existing runner. Recheck source, model, geometry and project snapshots before committing. Record the actual new preview media identities, even when they differ from the original selected examples. Do not regenerate the graph from a model or silently refresh model options.

For the first slice, permit only a terminal `draft_ready` task, no pending action/model call, an empty candidate list, and no active build/investigation mutation. Refuse an existing app with a clear conflict instead of silently replacing it. Later explicit replacement/recovery of an inconclusive task can use the same proposal mechanism; it is unnecessary for the first successful handoff.

Commit one candidate, an immutable handoff receipt, the exact captured planning options and per-block bindings, and a paused build at `awaiting_review`. Add a narrowly named `BuildStore`/`BuildManager` adoption method: initialize actual compiled/previewed evidence and selected candidate, publish the matching platform plan with an explicit handoff origin, reconcile current project state, and pause before label proposals or evaluation. Do not fabricate model calls or claim the investigation preview was a legacy planning operation. Store original task/revision/observation references on the durable build, not only in a log string.

Use the existing repository lock and authoring fingerprint/CAS pattern, but account for project, build and platform files as a multi-file operation. A small durable handoff transaction/reservation plus idempotent receipt must recover a process death without creating a second build or accepting a partial handoff. Revoke any approvals before publishing changed candidates. Failed preparation/preview leaves the app unchanged; interrupted commit must remain non-runnable until reconciled. This transaction needs an explicit design/test; sequential `save_candidates(); create()` alone is insufficient.

## Identity and review invariants

- Resolve every artifact below the task/revision root; verify content hash, MIME/size, revision ownership and the successful completed construction receipt. Never accept a client-supplied graph or artifact path as authority.
- Preserve block IDs/order/edges/params, model IDs and compiled identities, evaluation proposal, and frozen zone bytes. Only the disclosed source binding changes. Record original and rebound spec hashes plus an equality check over all other spec fields. Keep original sample source/pixel hashes and original preview immutable.
- Revalidate captured options/descriptors and current adapter identities. Drift requires rebuilding/repreviewing; never silently substitute a configured default model. Preserve per-block bindings for subsequent refinement/replay.
- Keep project annotations, reviewed flags, synthetic/fixture/data-origin metadata, source/group exposure, reserved acceptance data and evidence configuration unchanged. Do not copy samples into a fresh project to escape prior exposure. A fixture draft receives no label or approval shortcut.
- Initial preview remains development evidence. Show proposed metric/target for human review, especially a target such as `0.0`; acceptance eligibility and unscored multi-branch limitations remain enforced by the existing recipe. No fabricated labels or automatic target pass.
- A selected-sample preview does not satisfy evaluation's reviewed-data requirements. The existing 10–50-image evaluation gate remains; one image can yield a saved and previewable draft, but cannot immediately unlock a recorded run through this path. Local-trial approval is also explicit and currently requires a current evaluation.

## Native path and meaningful validation

Replace the placeholder with a proposal sheet showing the source scope, graph summary, exact preview, proposed metric/target and limitations. After acknowledged acceptance, load the returned `BuildStatus`, persist its origin/runtime association, and open the existing annotation/evidence review surfaces. Keep a link back to the immutable investigation timeline. A retry or app relaunch must resolve the same handoff/build. A button that only changes `runtime` to legacy would lose the necessary backend state and is not this implementation.

Focused tests should cover:

1. An actual generated test image and real compiled fixture pipeline: investigation construction → prepare/accept → saved candidate/platform bindings → real new preview → paused review; exact non-source graph equality and source hashes. Label this a protocol integration test, not a learned-model acceptance result.
2. Tampered artifact/hash, cross-task revision, failed preview receipt, changed media/model/geometry/task revision, active worker and existing candidates all reject without mutation. Preserve original ledger/artifacts byte-for-byte.
3. Duplicate requests, concurrent accept and crash injection between each persisted file: one receipt/build or safe incomplete state; no approved runnable partial app. Failed preview never commits.
4. Reserved acceptance exclusion and exposure retention; fixture metadata and annotation review flags unchanged. No evaluation, deployment, event persistence or alert dispatch during import. Explicit recorded-run call still rejects before approval.
5. Exact captured model bindings survive a subsequent guarded refinement and plan replay. Missing binding provenance fails, rather than falling back to settings.
6. Native request/response and relaunch tests: correct origin retained, review screen opens, network retry does not create a new build, stale proposal remains reviewable with a conflict. Follow with one visible native smoke using a real Apple Vision saved draft; no LLM call is needed to test handoff itself.

## Remaining decisions / limits

The first-slice empty-project restriction avoids deciding append-versus-replace semantics. Recovering a correct preview from an inconclusive investigation is separately useful but should be explicit. Evaluation target editing and low-sample sandbox running need product decisions if existing review controls prove insufficient; neither should be smuggled into import as approval. The frozen-source alternative would require changing both candidate/refinement source guards and their snapshot assumptions, so it is larger than the explicit rebind proposed here. The successful transferred draft is an actual executable candidate ready for human review—not a claim that the original describe-to-approved-app objective or production quality is already complete.
