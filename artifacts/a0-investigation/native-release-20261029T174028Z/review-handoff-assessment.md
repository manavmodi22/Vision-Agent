# Explicit draft review handoff — read-only assessment

Assessment against commit `4ef067339a9f8c7de3b3c7f4d2b91a4e6b0824aa`; no implementation or app mutation performed. Run4 and Run5 end `inconclusive` with successful OCR probes but no selected workflow. They are not eligible examples of this handoff.

## Smallest useful boundary

Add one human-only `POST /projects/{project_id}/investigations/{task_id}/review-draft`, one host handoff service, a durable idempotent handoff receipt, and an explicit native **Prepare draft for review** action. Do not add the operation to the model's decision union or MCP tools. Keep the task, its objective, receipts and frozen preview intact; do not manufacture or start a legacy `BuildStatus`.

The request should bind `expected_revision`, `workflow_revision_id`, `preview_observation_id`, expected project/candidate-state fingerprint and `client_request_id`. The result should identify the exact new project candidate index/hash, original workflow revision/hash, project snapshot and handoff receipt. It must not report a new successful preview or approval.

Initially reject a project that already has candidates or a deployment. This permits a bounded first handoff without silently replacing an existing app or defining a candidate merge policy. Existing-app replacement can be a separate explicit user choice later.

## Host validation and source rebinding

1. Under the project/lifecycle guard, require a quiescent `draft_ready` task with the exact selected revision and preview observation, plus the matching completed construction action. Reuse the correspondence rules at `engine/investigations/store.py:236` (`_preview_evidence`) and `:244` (`_ready_revision`) through a small public validation helper. Reject stale revisions, foreign tasks, missing/failed/partial receipts and concurrent legacy or investigation work.
2. Load the content-addressed revision record and its `spec`, `options`, `bindings` and `preview` references; verify hashes, ownership, preview/frame input hashes and current selected media membership. The immutable manifest is written at `engine/investigations/workflows.py:207` and includes these references. Never accept a replacement graph or model ID from the native request.
3. Recheck the saved model options against current capabilities (`engine/platform/planning_options.py:104`) and exact per-node bindings (`spec/model_bindings.py:6`). Check confirmed zone geometry against the captured zone data. Changed model registration, unavailable capability, changed media or changed zone geometry should fail visibly rather than silently substitute a model or geometry.
4. Create a host-owned copy of the saved spec using `inputs.source.path = "media"`. Investigation construction intentionally binds a frozen sample folder (`engine/investigations/workflows.py:146–159`), while `WorkspaceService.save_candidates` requires the project media folder (`engine/service.py:105–126`). Preserve all inference nodes, parameters and per-node bindings; any zone-path rebinding must retain identical confirmed geometry. Compile and compute a new candidate spec hash after rebinding. The frozen preview remains evidence for its original hash, never for this new candidate hash.
5. Persist the new candidate with `save_candidates`, preserving original task artifacts and label contents. That path already recompiles and invalidates evaluations/deployment state (`engine/service.py:55–62`). Keep the original metric/target labelled draft assumptions requiring review. Save a handoff receipt linking both hashes, options/bindings and the project fingerprint. Use a recoverable pending/completed receipt so a crash or duplicate request cannot append another candidate or lose provenance.

The first handoff need not run inference. It places a validated draft in review and clears any global candidate preview. A subsequent explicit preview uses the existing bounded project preview path (`engine/service.py:128`, `WorkspaceModel.swift:166`). This preserves actual selected-sample provenance and does not automatically expose held-out evidence or silently reinterpret the prior preview.

## Native reuse and the legacy boundary

Replace the current unavailable-handoff message at `InvestigationViews.swift:135–137` only for an eligible `draft_ready` state. Show the source-scope change and metric/target assumptions before sending the explicit request. On success refresh the returned project, select the returned candidate index, clear global preview/evaluation, and open the existing Dataset/annotation review experience. Keep the A0 conversation and frozen preview accessible as provenance. `AgentAnnotationReview.swift:11` already reuses the persistent dataset workspace; `WorkspaceModel.swift:214` and `:221` provide explicit evaluation and approval actions. The deployment service still requires an actual current evaluated candidate and separate approval (`engine/service.py:329`). No automatic labels, evaluation, training or deployment belong in handoff.

Do not route the button through `agent.start`, `agent.resume`, `BuildStore.create` or `continueBuild`; those are legacy orchestration. `AgentWorkspaceActions.swift:58` already excludes A0 from legacy continuation. If a later legacy-style execution plan is desired for refinement, publish a genuinely separate operation with the captured options and bindings. `PlatformStore.publish` currently infers `active_build` at `engine/platform/store.py:156` and can overwrite the supplied goal with that build's prompt. It needs an explicit no-inheritance path before use for A0 handoff; passing `build_id=None` is not sufficient. The smallest manual review handoff can retain bindings in its immutable receipt and defer that orchestration integration.

## Focused acceptance cases

- Exact ready revision imports once; retries return the same receipt/candidate.
- Run4/Run5-style inconclusive tasks, forged successful payloads, stale revisions and wrong observation/task IDs are rejected.
- Model/adapter/options, input-content or confirmed-zone drift is rejected.
- Source rebinding creates a new hash; the old frozen preview is never marked current for the project candidate.
- No existing candidates, reviews, annotation values, evaluations or deployments are overwritten by a rejected request.
- A successful handoff changes only the candidate/brief and explicit handoff records; labels remain human-controlled and approval remains absent.
- Native navigation selects the returned candidate and shows review, without creating a legacy build, invoking tools automatically or claiming measured quality.
