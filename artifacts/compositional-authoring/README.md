# Actual local planner acceptance

The final captured run passed both required composition cases and a requested crop/resize follow-up. [Final report](evidence-final/final-report.json) links to exported decisions, saved plans, real previews, model responses, and replay evidence. The local planner was Qwen3-14B Q4_K_M behind the `visionapp-planner` alias; inference used Apple Vision. Receipts identify the alias and native binary; the Qwen filename is corroborated by local server launch configuration, not a weights hash attached to each planner response.

| Captured case | Actual result | Planner calls | Elapsed |
| --- | --- | ---: | ---: |
| Left-half crop → 1200×400 resize → OCR → exact comparison | `ABC-990`, matched `true`, no events | 1 | 76.79 s |
| Whole-image OCR and barcode branches | `ABC-990` plus QR `VISION-AGENT-PARALLEL-QR`, no events | 2 | 86.30 s |
| Follow-up: right half → 900×300 resize | `WRONG-111`, original `ABC-990` comparison matched `false`, no events | 1 | 48.73 s |

The parallel-reader case required one semantic retry; both original responses and rejection feedback remain exported. The optional detector/OCR case was not run and is not counted as passed. [Full automated validation](full-tests-final.log): **1,137 passed, 2 skipped**.

The [installed native walkthrough](native-ui.json) separately verified describe →
actual cropped reading → visible Pass, then a conversational right-half refinement
→ actual `WRONG-111` reading → visible Fail. Model calls took 44.91 and 23.32
seconds. CUA accessibility states and screenshots verified the selected source
region and displayed expected/observed values. Initial file-picker timeouts were
recovered by reconnecting to the canonical app; no raw screenshot file was
exported. The [native payload checks](native-payload-receipt.json) also pass 263
release checks, including six captured frame/plan decodes. The original project
remains unchanged and the new walkthrough project stays unreviewed/unapproved.

These are actual local-model and native-inference checks on generated software fixtures. They establish prompt-to-composed-graph execution and one user-requested follow-up. They do **not** establish an adaptive experiment/optimization loop, recognition accuracy acceptance, or production performance. Imported labels remain unreviewed; no quality evaluation or deployment approval was created. The follow-up stops at `awaiting_review`.

The original refinement harness mistakenly compared `input_to_frame` with crop `xyxy`, expecting `[0.5,0,1,1]`. That field is `[offset_x,offset_y,scale_x,scale_y]`, so the right-half transform is `[0.5,0,0.5,1]`. [The original failed report](evidence-final/refinement/harness-failure-original.json) is preserved byte for byte. The assertion is corrected, and the captured successful refinement was revalidated offline. No LLM or inference rerun occurred; workspace hashes remained unchanged. The refinement evidence distinguishes pure patch reconstruction from replay of the unfinished build/review state machine.

To reproduce the read-only evidence export, choose a fresh output folder:

```sh
.venv/bin/python artifacts/compositional-authoring/export_evidence.py .visionapp/compositional-authoring/run-20261029T162251Z --output artifacts/compositional-authoring/evidence-recheck
```

The exporter checks source identity, original receipt hashes, preview semantics, typed graph replay and patch reconstruction. It preserves the failed report and copies fixture/evidence documents without settings or credentials.

`run_live.py` exercises the current planner through its normal MCP connection, imports source images through `WorkspaceService`, executes the proposed graph, saves it, and reconstructs the captured decision with effect-free replay. It does not use scripted planner replies or mocked recognition. **Prepare first; run only after production source edits and the native build have finished.**

Prerequisites:

- The repository `.venv` with project dependencies, including Pillow and OpenCV.
- The current executable at `app/.build/debug/VisionApp` on macOS. The script sets `VISION_APP_BINARY` to this exact path.
- A local OpenAI-compatible server at `http://127.0.0.1:1234/v1` listing `visionapp-planner`.
- The system Arial font at `/System/Library/Fonts/Supplemental/Arial.ttf`.
- Existing model assets, when needed, at `~/Library/Application Support/VisionApp/models` or `--models-dir`. The harness only reads them, disables Hugging Face network retrieval, and verifies their file sizes/modification times remain unchanged. It neither installs weights nor changes directory permissions. This metadata check is not a cryptographic proof of unchanged multi-gigabyte weights.

Run the two required cases from the repository root after source freeze:

```sh
.venv/bin/python artifacts/compositional-authoring/run_live.py --case required
```

Use `--case crop-reading` or `--case parallel-readers` for an individual rerun. `--workspace .visionapp/compositional-authoring/my-new-run` selects a new isolated directory; existing paths are rejected. `--source-identity HASH` optionally pins a known frozen source identity. Each case has a fresh project in that workspace. Existing user projects are never imported into the run.

The first generated fixture is 1200×200 pixels: `ABC-990` in its left half, `WRONG-111` in its right half. The goal asks for crop `[0, 0, 0.5, 1]`, then resize to 1200×400, Apple Vision OCR, and an exact comparison with no events or alerts. Assertions inspect the executed graph connections, actual adapter input size and transform, observed literal value, comparison result, excluded distractor, and absence of event storage.

The second fixture is 1600×600 pixels with printed `ABC-990` and an actual generated QR encoding `VISION-AGENT-PARALLEL-QR`. Both readers must run on the whole image in one candidate, each with its own saved model binding and actual Apple Vision observation geometry. Both expected values must be recognized. Generating a QR image does not bypass decoding: the runtime still invokes the native barcode reader. Generator/font versions and image hashes are saved in `fixtures/manifest.json`. These synthetic fixtures establish software behavior, not real-world recognition accuracy.

An optional real detector case is separate and never counted as passed unless run:

```sh
.venv/bin/python artifacts/compositional-authoring/run_live.py \
  --case mixed \
  --mixed-image /absolute/path/to/documented-people-and-text.jpg \
  --detector-model yolox-s-onnx-coco
```

This requires a preexisting image containing actual people and legible text and an installed available detector. It asserts actual positive person detection/count and actual OCR, plus independent model bindings on parallel branches. A missing model or image is an error, not a skip or substitute fixture pass. Record the source image's provenance alongside the resulting report before sharing it. No fixture-detector variant is included.

`report.json` contains deterministic assertion results, timings, explicit unrun cases, source/native identities, and references to the full evidence. `required_acceptance_complete` is true only when both required cases pass in the selected run. Original model requests/responses, retries, tool results, catalogs and failures remain in each isolated project's `agent-runs/<operation-id>.json` and immutable `platform/` artifacts. Compact reports do not duplicate those catalogs. Extracted `decision.json`, `result.json`, `preview.json`, and `replay.json` live under `acceptance-evidence/<case>/`.

Replay checks compare workspace content hashes immediately before and after pure reconstruction. The harness never marks imported annotations reviewed, evaluates quality, approves deployment, or publishes. It asserts those boundaries remain unchanged. Any failed assertion or planner/recognition exception yields a nonzero exit, preserving the original evidence; later required cases still run after an earlier case failure when setup permits. A source or binary change during a run invalidates the overall acceptance result.
