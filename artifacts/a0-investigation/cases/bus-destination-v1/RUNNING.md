# Running the frozen scene case

`artifacts/a0-investigation/run_case.py` is separate from the ongoing generated-fixture comparison. It uses the actual investigation manager, MCP transport, selected local planner and installed adapters. It does not start servers, install models, answer a user question, prescribe experiments, review labels or approve a draft.

Use Python from `.venv` and an already-running compatible local planner. The default Apple Vision executable is the retained canonical app; override `--native-binary` explicitly when comparing another native build. Both variants must use the same frozen source, model, native executable, system/objective prompts and budgets. Run sequentially in fresh workspaces:

```sh
.venv/bin/python artifacts/a0-investigation/run_case.py --variant original --validate-input
.venv/bin/python artifacts/a0-investigation/run_case.py --variant degraded --validate-input
.venv/bin/python artifacts/a0-investigation/run_case.py --variant original --model-url http://127.0.0.1:1234/v1 --model visionapp-planner
.venv/bin/python artifacts/a0-investigation/run_case.py --variant degraded --model-url http://127.0.0.1:1234/v1 --model visionapp-planner
```

`--media` can point to another copy of that variant; bytes, dimensions and decoded RGB pixels must match the predeclared manifest. `--output-dir` must be new; the default uses ignored `.visionapp/a0-investigation/case-…` storage. Do not publish the imported photographs or raw evidence without observing the provenance/licensing limitations in the manifest.

Each run imports exactly one image through `WorkspaceService`. Its sibling `evaluator-only/` folder retains the reference manifest outside the planner workspace. Only the generic case objective and imported image enter the project; the evaluator reference is read for scoring after execution stops. The output retains:

- `setup.json`, the exact system/objective prompts and their hashes, source identity, native binary hash, input/imported RGB hashes, model URL/alias and budgets.
- `execution.json` with actual actions/observations, `model-calls.json` with original requests/responses/failures, and immutable probe/workflow artifacts under `workspace/`.
- `selected-preview.json` and `report.json`, including selected revision/spec hashes, timings, exact reference scoring, mapped geometry, evidence-linked changed-action candidates and side-effect counts.

The reference check splits readings only on whitespace and requires the expected tokens once each, no extra text, and reading centres within the predeclared full-frame display envelope. Adapter coordinates are mapped using `input_to_frame` offset/scale. Missing previews/geometry and duplicate readings cannot silently pass. Draft status alone is not success.

Action-reference links are candidates for trace review, not proof of useful adaptation. Degraded-case uncertainty is deliberately **not automatically scored**: an awaiting-input or blocked result may be appropriate or unsupported, and needs review against its actual observations. Unexpected correct readings remain visible. Exit status 0 means the harness completed with unchanged source, not that the application or A0 passed. Interrupted runs retain captured state when cleanup can complete; SIGKILL or host loss can leave the durable workspace without a final report.

The model alias does not establish exact weights; pair results with the separate qualification receipt. This is one scene previously used in reader diagnostics plus a degraded derivative, not a pristine independent holdout, warehouse benchmark or production-quality claim. No live case run was performed while adding this harness.
