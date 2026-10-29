# Workflow-visibility replay: promising decision, not a built app

**The targeted change produced the predicted next step at this captured boundary.** The historical medium call 7 asked the user to choose regex filtering. With generic construction visibility added, the model requested `prepare_workflow` for `frame_sample -> crop -> OCR`, citing the actual successful crop observation `fd6fda6b9f5c484785dd9538378d1343` in both provenance and evidence fields.

Independent comparison of the captured ledger with actual wire messages/function schema confirms exactly three changed paths:

- `/context/action_contracts/prepare_workflow/description`
- `/context/workflow_capabilities`
- `/schema/$defs/PrepareWorkflow/description`

System prompt, task state, observations, grounding constraints, model, temperature 0, total 1,400-token allowance and native decision-function transport remain the same. The inventory names generic implemented operations and their semantics; it contains no fixture answer or task-specific routing. It explicitly separates graph capability from model readiness and explains that match does not filter original readings. Source `6a7d932897faf376a2b7f1360eaf1c3479741cd1ef73eda34f6ee4a3ff05ae6c` and the historical ledger stayed unchanged during execution.

The response completed with one `submit_decision` tool call, 659 generated tokens and 46.29 seconds elapsed. The actual tokenizer preflight counted 7,917 prompt tokens within the 16K window. Shape, revision and evidence references passed diagnostic validation. No action was dispatched or execution authority granted.

This supports the visibility hypothesis for this one decision point. It does not isolate which of the three related documentation additions mattered, establish deterministic general improvement, or prove the model can author a valid graph and finish honestly. The proposed chain is prose inside prepare_workflow, not a constructed workflow. The crop evidence covers only the supplied fixed layout.

The next bounded qualification is a fresh full investigation using the original objective/media and the same medium profile/budgets, with no injected replay answer. Require the agent to author the actual graph, run its preview, use that selected revision's evidence, and satisfy the exact exclusion reference. Any static-crop conclusion must remain limited to the tested layout. Preserve ask-user, malformed graph, wrong-preview, budget and unsupported-readiness outcomes as failures/incomplete results. Only after a successful full fixture trace should a separate shifted-layout case test adaptation or an honest limitation.

Code-review follow-up: the diagnostic source imported engine registry metadata into agent/investigation.py. Root assigned a pure-spec boundary fix preserving the exact inventory. That is separate from the completed diagnostic; record the new source identity for the fresh run and verify inventory equivalence. No production edits or inference were made by this audit.
