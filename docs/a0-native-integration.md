# A0 in the existing native goal composer

29 October 2026 · Native integration implementation. A0 remains an explicit experimental runtime; the legacy builder remains the default. Compilation and contract checks are distinct from live native UI acceptance.

The existing **Build my app** composer and Agent workspace dispatch to one runtime for the session. A0 uses durable investigation tasks and does not become a legacy `AgentBuildStatus`, project candidate, approval or deployment. There is no template tab.

## Runtime and persistence

`SettingsView.swift` exposes the native-only `vision.experimentalInvestigations` preference. It applies to new app sessions; existing sessions retain their persisted runtime. `AgentHomeView.swift` identifies the experimental selection before submission. `createAndBuild` captures the runtime when the user submits, creates/imports the examples, then starts that runtime. Existing legacy build records take precedence when restoring an unbound project; otherwise the investigation collection resolves the latest task. A saved A0 task is fetched directly.

`AgentWorkspaceStore.swift` keeps `AgentBuildStatus` unchanged. Its separate `investigation: InvestigationSnapshot?` and runtime state are implemented with `InvestigationWorkspaceStore.swift`. The selected task ID and runtime are persisted per project. A start request retains a stable `client_request_id` across uncertain transport failures. Acknowledged starts are not retried as new starts because a later polling fetch failed. A 4xx start rejection clears that pending request. Snapshot responses must match the selected project/task and cannot roll back a newer revision. No legacy refresh applies over an A0 session.

`AgentWorkspaceActions.swift` sends answers/resume to the current task and starts a new investigation only from a terminal task or an empty session. The composer cannot replace a running, paused, awaiting-input or unknown-status task. Unknown protocol versions/statuses do not gain mutation controls. Polling cancellation only stops the UI poll; pause/cancel call the backend explicitly.

## Actual API and DTOs

`engine/api/investigation_routes.py` implements:

| Operation | Request | Response |
| --- | --- | --- |
| `POST /projects/{project_id}/investigations` | `runtime_version: "a0.1"`, objective, stable client request ID, optional budget | `TaskState` |
| `GET /projects/{project_id}/investigations` | — | Task states, newest first |
| `GET /projects/{project_id}/investigations/{task_id}` | — | `{state, actions, observations}` |
| `POST .../{task_id}/resume` | expected revision, optional answer | `TaskState` |
| `POST .../{task_id}/control` | expected revision, action `pause` or `cancel` | `TaskState` |

`InvestigationDTOs.swift` decodes the current `spec/investigation.py` contract. State contains objective, task/project IDs, revision, stage, status, selected workflow revision, preview observation ID, budget counters/limits, pending action/model call IDs, latest observation IDs, question, stop reason, user answers and timestamps.

Statuses are `running`, `awaiting_input`, `blocked`, `inconclusive`, `interrupted`, `failed`, `cancelled`, `paused`, and `draft_ready`. Stages are `investigating` and `workflow`. `prepare_workflow` selects the workflow stage but does not claim a built or previewed application. A successful `construct_workflow` selects the immutable revision and actual preview receipt, then returns to investigating. A subsequent model finish decision can produce `draft_ready`. The native view does not infer that outcome from compiler validation or a running workflow stage.

Action records contain a `next_action` or `workflow_decision`, model-call ID, chosen action, decision summary, cited observation IDs, status and linked observation ID. Observation records preserve actual result type, status, payload, error and timestamp. Unknown action payload fields remain inspectable JSON rather than fabricated workflow types.

Pause, resume and cancel target the selected task and current expected revision. A conflict refreshes the snapshot and reports the failure; the UI does not silently repeat a mutation. Resume preserves counters and lets the agent choose a next action. It does not automatically repeat interrupted tools. Neither control body contains training or deployment approval.

## Native activity and vision evidence

`BuildView.swift` retains its two-column composer/evidence layout. The A0 branch uses `InvestigationActivityView` and `InvestigationControls` instead of the legacy plan/timeline/approval controls. The objective and answers come from task state. Each activity card shows the model's recorded purpose, actual observation summary, and the subsequent action **only when that action cites the observation**. A pending model call displays “Agent choosing an action,” rather than an invented tool execution.

`InvestigationEvidenceView` displays a selected observation or the selected draft preview. It uses `ImageCanvas`'s additive verified-image-data input; legacy path rendering is unchanged. Provisional OCR/barcode values retain Unicode and actual boxes/polygons on the transformed probe input. Detections use their returned class, confidence and geometry. These graphless observations do not invent workflow block IDs. Full value/geometry and execution identity disclosures retain recorded data. Zero results and errors remain actual observations. Returned truncated text is marked. Up to 200 full probe values are loaded from the immutable result artifact, with the shown count separate from the recorded total.

Image-only inspection receipts display the recorded image artifact without inferring overlay geometry. Multiple returned images currently display the first, explicitly labelled with the returned image count. An image displayed to a person is not represented as pixel input to the planner; an explicit `pixels_visible_to_planner: false` receipt is shown as such.

For a selected workflow, native presentation requires a completed construction action and matching completed observation, selected revision, equal spec/preview hashes, exact ordered media IDs, validation and preview success, and one nonempty frame result for each selected image. It then renders the actual `RunResult` with existing reader geometry, text comparison and text output components. Missing or mismatched evidence produces “Draft receipt unavailable,” not a ready claim. Preview events are identified as unsaved/undispatched outputs. Model scores and development previews do not become measured quality.

## Task-owned artifact boundary

There is no investigation artifact HTTP endpoint. The native local application uses `InvestigationArtifacts.swift` under the supervisor's canonical data root. Only the selected project's/task's content-addressed `artifacts` directory and selected workflow revision's frozen `media` directory are eligible. Artifact IDs, MIME type, declared byte length and SHA-256 must match. Workflow images must match their exact frame path, input reference and source hash.

Reads walk directory descriptors with `openat` and `O_NOFOLLOW`, reject symlinks at every child component, require bounded regular files of at most 64 MiB, and verify the actual bytes before returning them. The canvas receives verified bytes; it does not reopen an unchecked model-supplied path. A read/hash failure leaves the result text inspectable and reports image unavailability. No broad filesystem search or arbitrary source-path rendering is used for A0 evidence.

## Draft boundary and remaining acceptance

A verified selected draft remains **Draft ready · review required**. This integration does not write project candidates, annotations, deployment IDs, evaluation outcomes or approval fields. Review handoff is explicitly unavailable in the experimental runtime. A later host operation must materialize the exact revision as a reviewable project candidate before the existing reviewed evaluation and approval flow can be used; the UI does not simulate that operation.

`InvestigationContractChecks.swift` covers DTO/status semantics, causal observation links, selected preview correspondence, stale responses, exact mutation bodies, Unicode/region preservation, persisted runtime, and task-owned artifact integrity/path boundaries. `PlatformContractChecks` accepts `--investigation-snapshot <path>` for real backend snapshots; a `draft_ready` snapshot must contain its matching valid preview. Existing native checks continue to exercise legacy build/plan decoding and rendering contracts.

Verification at published commit `4ef0673`: native CI passed 291 checks. The local Release binary passed 293 checks with the actual Run4 and Run5 snapshots, both containing four Apple OCR readings and geometry. [Build, source and binary identities](../artifacts/a0-investigation/native-release-20261029T174028Z/report.json) are retained. Neither snapshot contains a selected draft. The release build did not replace or relaunch an app bundle.

The development app visibly displayed Run4's actual image and four OCR quadrilaterals/readings, and a fresh objective was submitted through its composer to start Run5. [Native observations](../artifacts/a0-investigation/native-ui-observations.json) distinguish that visible check from backend evidence. Run5 ended inconclusive after exceeding the then-active 8K context budget. Final UI inspection and a current-package relaunch await an unlocked Mac. Live acceptance still needs a useful causal revision, pause/resume/cancel behavior and an inspectable selected draft where the model reaches one. Native compilation or decoding a captured backend snapshot alone does not establish that complete flow. No canonical application packaging or deployment is performed by this change.
