# Next planner experiment: expose construction capabilities before changing transport

**First test a small visibility change on a frozen post-crop decision. Do not infer that a bigger model or a framework rewrite is necessary.** The current evidence distinguishes three issues: a real missing output-selection primitive, incomplete construction documentation before the construction stage, and incorrect model decisions despite available evidence.

## What the traces establish

- The first native-function run made a valid `frame_sample -> OCR -> match` graph, saw a full preview containing all four readings, later found a crop returning only `QZ-4817`, and finalized the unrevised graph. The match contract explicitly said it does not remove readings. That false isolation claim is model noncompliance; the later omission of selected graph/preview from fresh contexts was also a host visibility weakness. Source 71 now anchors those selected contents.
- The medium source 71 run again discovered the effective crop, but never requested construction. Its final context included the full-image readings and successful crop. It instead offered an unverified regex-filtering preference question. There was no exhausted budget or missing user fact recorded. This is incomplete planning, not an output-transport failure.
- In that exact call 7 context, `action_contracts.prepare_workflow` contains only required fields and the evidence_ids/summary field types: **no action description**. Full node semantics appear only after `prepare_workflow` changes stage. The system mentions the transition, but the investigating model is not given a compact inventory showing which operations a saved graph can express. Its `filter` search restricted to `kind=model` returned zero; that says nothing about graph tools or an uninspected regex capability.

References: `gpt-oss-function-run-review/`, `gpt-oss-medium-run-review/`; `spec/investigation.py: PrepareWorkflow`; `agent/investigation.py: action_contracts, node_contracts, _run_steps`; `agent/investigation_docs.py`.

## Smallest falsifiable implementation experiment

Add **model-visible documentation only**, derived from existing graph contracts: a compact `workflow_capabilities` inventory available during investigation, including each operation's input/output kinds and limiting semantics. State that `prepare_workflow` requests the separately typed graph-authoring/actual-preview stage. Document that crop/resize operations can be represented in a saved workflow, OCR reads all text in its input, match creates comparison events, and static crop does not locate a field dynamically. Keep unsupported operations absent or explicitly unavailable. Do not include fixture values, prescribe an action sequence, or auto-copy a probe into a graph.

Use medium run task `a006b3b662da4b3a8970989f3321692b`, captured call 7, as the first paired diagnostic. Historical control is its saved ask_user response. Treatment changes only those general construction docs; retain exact state/evidence/grounding, model, temperature 0, medium reasoning 1024 per block, native decision RPC and total 1400 output allowance. Record input diff and actual template/token budget. No dispatch in the first comparison.

The prediction is explicit: the added information should let the model choose a valid construction-stage request instead of asking an implementation preference or repeating the identical probe. A different question is not automatically wrong if it identifies a necessary user fact. If the model still cannot take a useful construction step, the visibility hypothesis is not supported by this case. One positive decision is only a reason to run the next bounded trace, never acceptance.

For a full trace, require model-authored preparation -> typed graph -> actual preview -> evidence-grounded final decision. The selected graph must use its own effective transformations; successful probes cannot stand in for it. Test a second supplied layout where the previous static crop is wrong: the agent must revise, acquire evidence, or state a real limitation rather than claim general extraction. Keep independent references outside the prompt.

Protocol tests should verify both model stages receive truthful operation semantics, no schema/reference authority is widened, source/media binding and reservation-before-effect remain intact, the exact model graph reaches preview, and restart/replay cannot turn an unknown prior effect into another dispatch. Existing real-fixture integration tests can cover execution; label scripted decisions as protocol tests, not planner acceptance. Verify actual template budget with the added docs.

## Independent RPC versus native tool history

The current `decision_function` mode starts each call with system + authoritative context and one forced `submit_decision` function. It has solved the observed final-channel transport failure, but discards prior assistant/tool-turn continuity; a raw saved transcript is not automatically model-visible. The selected-workflow anchor addresses one concrete loss. It does not prove that standard conversation history would improve planning.

If the documentation-only experiment fails, the next isolated transport experiment can retain the same one-function dispatcher while carrying actual assistant tool_calls/reasoning plus correlated tool-role outcomes between decisions. No new CV tool registry or orchestration framework is required. Use only completed host receipts as results; never invent success for pending/interrupted actions. Keep current state and grounding authoritative, one action at a time, and the same budgets. Compare on the same captured boundary before attempting a full task.

For an ongoing Harmony tool conversation, preserve assistant reasoning/tool-call messages and tool_call_id-correlated results until a final answer; do not silently summarize away required in-progress history. Stop if the real context budget cannot hold it. The present independent RPC is a different explicit protocol, not a malformed continuation. [OpenAI Harmony continuation guidance](https://developers.openai.com/cookbook/articles/openai-harmony). A successful native-envelope diagnostic alone does not justify changing that protocol.

## Missing output primitive versus model error

`GraphCandidate` has no explicit app-output binding. `engine/runtime/executor.py: execute_image` aggregates every TextValue into `FrameResult.texts`; `compare_text` returns comparison/event data, not a filtered TextValue. Thus an event match cannot select one app field, and adding a text-filter node alone would still leave upstream readings in the current aggregated output.

For general full-image field selection, the product needs a separate typed app-output projection/binding, with any supported text-selection operation feeding it while original observations remain preserved as evidence. Regex matching would need a real bounded contract and runtime, not approval of a proposed word. Dynamic semantic field extraction remains a separate capability question.

That missing primitive does **not** prevent this fixture's existing static `frame_sample -> crop -> OCR` solution. Conversely, the static crop does not establish arbitrary-layout applicability. The next experiment should test whether the planner can construct the supported, limited solution before enlarging the executor's semantics or claiming the broader goal is solved.

This note is read-only assessment. No inference, production source edit, default-model change or acceptance claim was made.
