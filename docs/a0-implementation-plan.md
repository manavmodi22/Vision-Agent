# A0: an observation-driven application builder

29 October 2026 · Implementation proposal; no production changes or new execution claims

This plan implements A0 from [the revised product proposal](agent-builder-proposal-2026-10-29.md). The deliverable is a persistent local agent that chooses an experiment, receives its actual observation, decides what to do next, and can produce a previewed application draft or a specific blocker. A complete graph response followed by host-selected execution does not satisfy this milestone.

Production is currently frozen pending the existing checkpoint. The changes below are proposed work after that checkpoint, not changes made by this document. Source references describe the inspected working checkout.

## Architectural decision

Use the existing local model client and structured output library to request **one typed next action at a time**. Execute that action through a new, narrow MCP investigation boundary. Persist the observation before the next model call. The model chooses discovery, inputs, capability, experiment, revision, clarification and stopping. The host chooses neither a problem family nor the next experiment.

The action loop does not require a new agent framework. Typed next actions make the spike inspectable and work with the existing local JSON-output setup. Native model tool calling can replace that transport later without changing task state or execution receipts.

The initial model context contains the user's objective, project identity, a small development-media summary, the action vocabulary, current state and remaining budgets. It does **not** contain every model manifest, every block schema or a suggested OCR/detection route. Discovery is an action selected by the model. Tool descriptions express capabilities, constraints and input/output types rather than customer use cases.

There is one implementation-selected action dispatcher, keyed by action kind. Capability adapters dispatch by registered capability ID and typed input contract. Neither dispatch mechanism interprets task wording. There must be no `if warehouse`, `if OCR goal`, fixed improvement ladder, regex routing or model-generated instruction that bypasses host policy.

## Narrow but real A0 surface

A0 supports imported development images, currently executable local adapters, static image preprocessing, the existing compiled graph language, and the existing result canvas. It does not add detector-driven crop collections, joins, temporal tracking, arbitrary code, installation or training. Those are explicit capability gaps the agent can discover and report. This limits the executable vocabulary, not the agent's control over experiments.

An experimental crop or model choice is an agent hypothesis, with source observations and geometry recorded. It need not have been literally dictated by the user. It does not authorize changing the requested output coverage, inventing ground truth or claiming accuracy. Keep this distinction from the current conversational patch guards, which intentionally accept only explicit parameter edits.

An A0 application deliverable is a versioned, compiled, actually previewed **draft requiring review**. Existing deployment and independent acceptance remain separate. A0 can demonstrate adaptive investigation without pretending that one inspected example qualifies a warehouse application.

## Typed next-action contract

Add `spec/investigation.py`. All envelopes use `extra="forbid"`, finite numeric values, bounded strings/collections, explicit schema versions and discriminated unions. The model returns:

```text
NextAction {
  schema_version: "a0.1",
  state_revision: integer,
  decision_summary: short string,
  based_on_observation_ids: ObservationId[],
  hypothesis_update?: { id?, statement, supported_by[], contradicted_by[] },
  action: InvestigationAction
}
```

The host supplies task/project IDs and issues the durable action ID after validating the response. `decision_summary` is a concise, reviewable justification, not hidden reasoning. Referenced observations must belong to this task and have been included in a model-visible context or explicitly inspected. A hypothesis update cannot assert tool results or change host counters, user requirements, labels, hashes or approval state.

| Action discriminator | Typed arguments | Actual result and boundary |
| --- | --- | --- |
| `discover_capabilities` | `query: string`, optional capability kind and input/output type filters, `cursor?`, `limit <= 8` | Compact capability IDs, descriptions, readiness categories and continuation cursor. Search the registered catalogue by descriptor metadata; search is not task routing. No inference or installation. |
| `inspect_capability` | `capability_id` | One versioned descriptor, exact parameter/input/output schemas, provenance, hardware, known limitations, eligibility and descriptor hash. Loading a descriptor grants no execution authority. |
| `inspect_media` | `selection: inventory | explicit_media_ids`, `media_ids <= 3`, `representation: metadata | pixels` | Stable media IDs, dimensions, source/pixel hashes, development membership and owned image artifacts. Pixel delivery requires a genuinely multimodal planner transport; otherwise return `pixels_not_visible_to_planner`, not a fabricated visual summary. |
| `run_probe` | See `ProbeRequest` below | An actual provisional adapter/VLM execution with receipt, result artifacts, source association, timing and explicit errors. No complete app or candidate commit is required first. |
| `inspect_observation` | `observation_id`, `view: values | geometry | image | overlay | error`, bounded item IDs/page size | Deterministic projection of saved output, or owned image artifacts. No new inference unless the model separately chooses a probe. No silent truncation: return counts, truncation indicator and cursor. |
| `construct_workflow` | `parent_revision_id?`, `graph: GraphCandidate`, `evidence_ids[]`, concise `change_summary` | Immutable draft revision, selected capability bindings and compiler validation observation. Save invalid proposals with diagnostics; they do not become runnable revisions. Host binds imported source and confirmed zone paths. |
| `preview_workflow` | `workflow_revision_id`, explicit development `media_ids <= 3` | Actual compiled execution on those samples, including `RunResult`, original-coordinate evidence, timing, warnings and output artifact IDs. No event persistence or external dispatch. |
| `ask_user` | One question, missing fact/label identifier, affected requirement IDs | Persist a paused question. The answer resumes this task; no alternative implementation is selected by the host while waiting. |
| `finish` | `outcome: draft_ready | blocked | inconclusive`, `workflow_revision_id?`, evidence IDs, limitations, concise result | Host verifies the requested terminal condition. `draft_ready` requires a current validated revision and actual preview receipts; it never sets deployment approval or `promotion_eligible`. |

`ProbeRequest` is a discriminated union, not arbitrary tool names plus untyped arguments:

```text
AdapterProbe {
  kind: "adapter",
  capability_id, inspected_descriptor_hash,
  inputs: [{media_id, source_sha256, transforms: [Crop | Resize]}],
  request: DetectionRequest | OcrRequest | BarcodeRequest,
  hypothesis_id?, compare_with_experiment_id?
}

VisualProbe {
  kind: "visual_judgement",
  capability_id, inspected_descriptor_hash,
  input: {media_id | observation_image_artifact_id, source_sha256},
  question, labels: bounded explicit strings,
  hypothesis_id?
}
```

For adapter probes, the selected capability must match the request's registered adapter/model/task and current eligibility. Reuse the versioned request union in [`engine/adapters/contracts.py`](../engine/adapters/contracts.py). The model cannot supply a Python module, model directory, server URL or arbitrary filesystem path. Transforms are a bounded ordered list with validated pixel sizes and normalized rectangles; record their composed input-to-source map and the actual transformed pixel hash.

The existing VLM API is a bounded labelled judgement with a reason, not general image understanding or a new ground-truth oracle. Expose exactly that contract through `VisualProbe`, using [`engine/llm_client`](../engine/llm_client/__init__.py), and return its identity scope and warnings. No configured/usable VLM means this probe is unavailable. A text-only planner can still inspect actual structured OCR/detection observations, but its trace must not claim to have seen pixels. Direct multimodal image delivery needs a separately verified adapter path; JSON artifact URLs alone do not constitute visual input.

Model-specific options are supplied on demand by inspected descriptors. Keep the next-action schema small; do not embed every manifest and workflow schema in every call. `construct_workflow` may use a separate typed generation call selected by that action: the model first chooses construction, receives the exact currently supported graph schema, then supplies the revision. Count and capture both calls. This is schema loading, not a host decision to build a particular workflow.

## Model-visible observations

Add a common envelope around existing inference and preview results:

```text
Observation {
  id, action_id, experiment_id?, task_revision,
  status: "completed" | "failed" | "cancelled" | "stale",
  result_type, artifact_refs[], input_refs[],
  executed: boolean, summary: deterministic bounded projection,
  total_items, returned_items, truncated, next_cursor?,
  identity_refs[], timing, warnings[],
  error?: {code, message, retryable, failed_stage}
}
```

Use [`InferenceResult`](../spec/inference.py) for actual adapter values, geometry, input pixels, execution identity and timing. Use `BlockInference.input_to_frame` and the same coordinate mathematics as [`engine/runtime/executor.py`](../engine/runtime/executor.py) for transformed inputs. Derive stable result-item IDs from experiment ID and output index; retain parent media and observation IDs. Do not invent physical object identity from a frame-local detection.

The next model call automatically receives the latest bounded observation summary, including whether the adapter ran, result counts, a bounded value sample, warnings and error details. The agent can fetch the remaining values or images with `inspect_observation`. Persist the exact context projection and image attachment hashes so the acceptance trace establishes what information the model actually received.

Keep three claims separate: the tool executed; the tool observed a value; the task output was correct. Empty OCR output is a successful execution with no readings. A detector confidence is not evaluation accuracy. A visual judgement remains a model assessment. Reviewed development references, when available, retain their human/provenance labels and are never replaced by the model's opinion.

## Persistent state and storage

Add `engine/investigations/store.py`, initially using the repository lock and atomic-file patterns already used by the build/platform stores. Store under a separate project-owned `investigations/<task_id>/` directory; do not overwrite legacy operation files or reinterpret their hashes.

| Object | Contents and writer |
| --- | --- |
| `TaskState` | Objective and original user messages; requirement IDs with explicit source; task revision; status; current hypothesis summaries; selected workflow revision; unresolved questions; counters; input snapshot; last committed observation cursor; pending action ID. Host owns status, counters and receipts. |
| `ActionRecord` | Validated model response, state/context hashes, model identity evidence, reservation, canonical argument digest, start/end status and receipt reference. Append before dispatch. |
| `Experiment` | Agent-selected question/hypothesis, input IDs, exact transforms and capability settings, identity snapshot, immutable resulting observation references. Failed experiments remain visible. |
| `WorkflowRevision` | Parent ID, complete typed graph, host-bound spec, model bindings, compile result, evidence references and content hash. Preserve all previous revisions. |
| `Observation` / artifact | Immutable execution or validation output. JSON and owned image artifacts have content hashes and byte limits. Model summaries refer to these; they are not substitutes for them. |

Maintain a short task summary for the next decision; raw history stays in immutable records and is retrieved when needed. Separate user constraints from agent assumptions. A model may retract its own hypothesis. It may not silently weaken a user acceptance target or convert a missing requirement into an optional one.

Snapshot external inputs separately from the investigation's own writes: development media and pixels, annotation/evaluation configuration, confirmed zones, settings, selected capability identities and source/recipe identity. Do not invalidate every step because the task wrote its own observation. A user edit, changed pixel, changed selected model or changed code invalidates dependent evidence and requires a recorded rebase/reprobe decision. An unrelated new catalogue entry need not invalidate old receipts; the selected descriptor/identity must still be rechecked before execution.

## Loop, budgets, resume and termination

The new `agent/investigation.py` loop performs only this control sequence:

1. Load current task state, verify ownership/lease and external-input snapshot, build a bounded context and persist its projection.
2. Ask the local model for one `NextAction`, recording the actual request/response and usage.
3. Validate type, revision, references, capabilities, policy and remaining resources. Reserve action cost before dispatch. Invalid output produces a typed validation observation for the model, not a different host-selected action.
4. Persist an action intent, execute its registered handler, then atomically persist the observation and update task state/counters.
5. Feed that observation into the next decision unless the chosen action paused or terminated the task, or a host stop invariant fired.

Proposed spike defaults are 16 decision steps, four additional schema-repair calls, six probes, three images per probe, 18 total adapter-image executions, three workflow previews, and 15 minutes of active work. Discovery/inspection also consumes steps; repeated failures consume budget. Make the envelope configurable before a session and report actual usage. These are initial bounds to measure on this Mac, not performance promises.

Use a serial owned inference worker so planner/VLM/detector memory use is explicit. The current `run_inference` checks deadlines before and after backend execution; it cannot preempt a blocked native/model call. An asyncio timeout alone is therefore insufficient. The A0 worker needs an owned-process deadline/termination boundary, late-result quarantine and a receipt distinguishing timeout from an empty result. Capture startup/model-load costs; do not hide them by reporting only kernel inference time.

Persist cumulative counters across clarification, retry, crash and resume. Reopening the task does not reset the allowance. Reserve before executing; a crash consumes the reservation until reconciled. Reuse a completed matching action receipt on resume. A persisted but uncertain in-flight read/inference action is marked interrupted and reconciled; rerunning requires a new attempt ID and remaining budget, never a fabricated exactly-once guarantee. This A0 tool set deliberately excludes irreversible external effects.

Guard against duplicate canonical actions returning the same observation with no new inputs. Return a `no_new_information` observation once, then end the run as inconclusive if it repeats. Do not automatically select another model, run training or relax thresholds. Host stops are mechanical: cancellation, budget/deadline, unrecoverable state corruption or stale authority. Evidence-based stopping and missing-capability decisions belong to the model.

`finish(draft_ready)` requires a valid current workflow revision, a successful actual preview tied to that exact revision and input snapshot, and an explicit limitations statement. It indicates a usable draft, not satisfied production acceptance. `blocked` names the missing capability/input and supporting observation; `inconclusive` retains the best artifacts and unresolved uncertainty. A failed probe is normally an observation that allows a new decision, not an automatic terminal build failure.

## Reuse points and deliberate replacements

| Existing code | A0 treatment |
| --- | --- |
| [`engine/capabilities`](../engine/capabilities/__init__.py), [`spec/capabilities.py`](../spec/capabilities.py) | Reuse actual descriptors, readiness/provenance and `validate_experiment_capabilities`. Add paged search and one-descriptor MCP handlers. Installed-but-unchecked inference can be a labelled bounded probe; it does not become production-ready by declaration. Cache discovery metadata per task without promoting cached readiness into execution authority. |
| [`mcp_server/server.py`](../mcp_server/server.py) | Reuse `block_schema`, source authorization concepts and existing typed tool implementations. `frames_sample` currently returns paths, not pixels, and only the first visible rows; add opaque-ID development selection and explicit pixel artifacts. New tools must enforce source membership themselves. |
| [`mcp_server/evaluation.py`](../mcp_server/evaluation.py), [`engine/eval/protocol.py`](../engine/eval/protocol.py) | Reuse reserved-acceptance exclusion and exposure bookkeeping. Every probe/inspection must resolve only development IDs and mark pixel exposure before returning content. The agent cannot inspect acceptance pixels through a new image-artifact shortcut. |
| [`engine/adapters/registry.py`](../engine/adapters/registry.py) | Call `run_inference` on owned transformed pixels with expected identity hashes. This is the provisional-experiment service the present graph-first planner lacks. Keep actual adapter result contracts and cancellation checks. |
| [`engine/llm_client`](../engine/llm_client/__init__.py) | Reuse bounded local VLM preflight and labelled judgement where configured; record the actual identity scope. Do not claim the existing classification interface is general image description. |
| [`agent/recording.py`](../agent/recording.py), [`agent/mcp_client.py`](../agent/mcp_client.py) | Reuse model recording and real MCP transport. Add an investigation binding and dispatcher result envelope. Current `MCPTools` extracts structured JSON; image artifacts require explicit transport/attachment support, not an assumption that existing calls deliver images to the planner. |
| [`engine/compiler`](../engine/compiler/__init__.py), [`agent/graph_authoring.py`](../agent/graph_authoring.py), [`spec/model_bindings.py`](../spec/model_bindings.py) | Reuse typed composition, capability bindings and compilation. Construction returns a revision/diagnostic observation. Preview accepts explicit selected development inputs rather than implicitly taking the first five images. |
| [`engine/runtime/executor.py`](../engine/runtime/executor.py), [`engine/runtime/__init__.py`](../engine/runtime/__init__.py) | Reuse real execution and coordinate mapping. Implement an explicit-input preview wrapper that retains the current acceptance exclusions and usage accounting. Never call the lower-level executor without those checks. |
| [`engine/platform/store.py`](../engine/platform/store.py), [`spec/platform.py`](../spec/platform.py) | Reuse immutable artifact, event and hash conventions. Add investigation-aware records and binary image references. Existing `ArtifactContent` is JSON and `PlatformReplay` requires a `BuildPlan`; neither should be misrepresented as supporting pre-graph investigations without additive contracts. |
| [`agent/machine.py`](../agent/machine.py) | Keep existing approval and evaluation authority. Add a separate investigation state/authorization model; do not broaden old phase allowlists until every exploratory action accidentally becomes permitted in legacy phases. |
| [`agent/planner.py`](../agent/planner.py), [`agent/executor.py`](../agent/executor.py) | Preserve legacy entry points and replay. A0 bypasses their host-selected discover → full graph → execute sequence. The new model loop owns when discovery, probing, construction and preview occur. |
| [`engine/builds/manager.py`](../engine/builds/manager.py), [`agent/build_orchestrator.py`](../agent/build_orchestrator.py), [`engine/platform/experiments.py`](../engine/platform/experiments.py) | Bypass host-authored experiment stages, scalar best-candidate selection and prescribed training offers for an A0 investigation. Reuse existing reviewed evaluation/deployment handoff only after a draft is explicitly selected. Failed probes return to the agent rather than entering `_scored`'s training branch. |

Current request-to-template selectors and graph intent regex checks must not become the A0 strategy engine. Structural validity, source ownership, artifact binding and approval checks remain deterministic. Task understanding is represented as sourced requirements and agent hypotheses, with unresolved semantic questions surfaced explicitly. Do not weaken legacy validation or replay semantics to fit the new loop.

## API and native path

Add `mcp_server/investigations.py` for captured action dispatch and `engine/api/investigation_routes.py` for start/status/resume/cancel/artifacts. A versioned A0 route or an explicit runtime-version field is an implementation switch, not a task classifier. Existing builds continue using their stored runtime version. A0 should be usable from the app's existing goal composer; an internal feature switch selects this runtime consistently for the whole session.

Extend [`AgentWorkspaceStore.swift`](../app/Sources/VisionApp/AgentWorkspaceStore.swift) and its status DTO with an optional investigation summary: task revision, current action, budget remaining, latest observation, selected workflow revision and stop reason. The UI polls durable status as it already does; reconnecting must display an active/interrupted task rather than inventing completion.

Reuse [`AgentTimelineView.swift`](../app/Sources/VisionApp/AgentTimelineView.swift) for captured calls, but show the purpose, actual finding and chosen next step as linked records. Add an image/overlay artifact view; the current artifact sheet only displays JSON. Use the existing image canvas and inference/result DTOs for actual regions and readings. A model sentence that says it inspected an image is insufficient: the visible record should link the image artifact actually supplied to the planner or VLM.

When the agent finishes, show a previewed draft with its workflow revision, source contract, output types and unresolved evidence. The existing review/evaluation/approval experience remains the path to recorded operation. Do not label A0 investigation completion as a deployed app or automatically enter `_run`'s operating phase.

## Real acceptance trace design

The acceptance harness invokes the configured local planner and real adapters through the same new MCP handlers used by the app. It records raw actions, exact model-visible contexts, source/pixel hashes, capability identities, timings, errors and workflow revisions. Scripted model actions remain useful unit tests but cannot satisfy the A0 exit criterion.

Choose unfamiliar, licensed development imagery with a human-audited reference suitable for at least one installed adapter. Do not hard-code that image, task or desired action sequence into the runtime or system prompt. A printed-label scene is an economical first fixture because actual local reader adapters exist; it is a test case, not an application route. Keep acquisition/provenance, real versus staged/synthetic status and the human reference in the trace manifest.

**Positive trace:** the model discovers capabilities, inspects the relevant descriptor, selects its own bounded experiment, and receives the real result. The first attempt must expose an actual useful limitation—for example missed text, extraneous readings, unsuitable resolution or unavailable geometry. The agent inspects the observation and chooses a relevant different action: another compatible capability, a different input/transform, a visual judgement, or construction of a different workflow. The next real probe/preview records the effect. It finishes with a compiled, previewed draft and bounded claims supported by the supplied evidence.

The harness must not fabricate the first failure or force a particular crop/model/order. If the first chosen approach succeeds and the agent finishes immediately, that may be a good product outcome but does not demonstrate the adaptive A0 exit criterion; retain it and run another predeclared unfamiliar case. If no case produces a justified observation-driven revision, A0 has not passed.

**Failure trace:** use the same goal with genuinely unreadable/insufficient pixels, or make an otherwise relevant capability genuinely unavailable in an isolated test configuration. Discovery/probe returns the actual condition. The model may choose a feasible alternative or request a specific missing input; it must eventually stop within budget with a supported blocker/inconclusive result. Retain the failed receipts and absence of a passing/approved application. A timeout must not turn into invented OCR, and unsupported detector-driven associations must not turn into a claimed static-crop solution.

Add a counterfactual pair using the same prompt with different evidence, or the same media with one tool unavailable. Compare the model's next actions after the changed observation. Require a relevant change with references to information actually delivered, not just extra random calls or changed prose. The host action dispatcher and prompts remain frozen across the pair.

Pass criteria for the architecture spike:

1. At least one real trace contains a model-selected experiment, its captured observation, and a subsequent materially different model-selected action justified by that observation.
2. The final draft's actual preview output is checked against the predeclared reference; report correctness and limitations separately from loop success. No broad quality claim follows from this sample.
3. The retained failure trace stops honestly and within budget; no fallback result, label modification, approval or external effect occurs.
4. Kill/restart after a completed probe and after an action reservation; verify receipt reuse/reconciliation, retained budgets, and no duplicate committed observation. Dry replay reconstructs decisions/artifact references with `effects_executed=false`.
5. Report model/tool latency, complete task latency, context bytes/tokens, model loads, peak memory where measured, retries, user interventions and all stopping reasons. Qualify the planner for this loop from those measurements rather than existing graph-output results.
6. Visibly run one session in the native app: submit a goal, inspect actual findings and the next action, reopen the task, and inspect the final draft or blocker. An HTTP 200 or a plausible activity list is not enough.

## Five-day spike sequence and handoff

Use one agent/backend owner with runtime/vision support. Day 1 delivers the action/state/observation contracts and durable empty loop; day 2 delivers real discovery and provisional inference receipts; day 3 connects those observations to subsequent local-model decisions and workflow revision/preview; day 4 covers interruption, budget, stale-input and protected-data tests plus the native activity path; day 5 runs the frozen positive/failure/counterfactual sessions and writes the evidence report. These are work slices inside the proposed time box, not guarantees that each day will pass its exit check.

The unit suite should test policy boundaries, immutable state, action idempotency, input transforms, source membership, acceptance isolation and honest error handling. Integration tests should execute actual fixture adapters and compiled previews. Only the live, frozen local-model traces establish that action selection is observation-driven.

If the time box ends without that trace, deliver the runnable code, failed traces, measured bottleneck and next estimate. Do not rename graph generation as A0. A successful spike yields the evidence needed to scope A1 media investigation, A2 data-dependent composition and A3 diagnosis; it does not complete those milestones.
