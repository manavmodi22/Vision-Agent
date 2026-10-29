# Existing-adapter slice 1: validation receipt

The common adapter slice is implemented without new production dependencies, model choices or native bridge protocol changes. See `docs/adr/0014-common-adapter-evidence.md` for the additive response schema, input-space coordinates and identity limits.

## Deterministic verification

- 234 tests passed in 59.41 seconds across core, service, live runtime/API, model selection, platform execution and refinement integrations. The final tests include artifact mutation with restored mtime, an actual loader-cache exercised with stub model construction, per-provider cache separation, literal/duplicate OCR retention, crop/resize mapping, late-result cancellation, missing bridge rejection and old-record decoding.
- Strict mypy passed 27 source files; Ruff passed all changed core/test files. Logs are `.visionapp/common-adapter-pytest.log`, `.visionapp/common-adapter-mypy.log` and `.visionapp/common-adapter-ruff.log`.
- An earlier broad run had two fixture failures because a manually assembled multi-branch compiled graph omitted the new identity map. The fixture now merges those maps; no runtime bypass or fallback was introduced. The final suite above is green.
- `frame-result.schema.json` confirms `inferences` is optional for old records. The existing live retention calculation includes serialized FrameResult bytes, so the added evidence remains subject to existing storage caps.

## One actual existing-model call

`smoke_existing.py` ran exactly one crop → resize → OWLv2 call on the previously acquired NVIDIA Warehouse_026 real preview. It requested only `person`, with confidence threshold 0.15. No project, annotation, review, evaluation score, approval or app event was created.

- Shared runtime source before/after: `2263a8b2e6af45ec6dfadb0be23b526e0fe1f4f5b947c5670ea6cd9f1e2e9d15`.
- Model identity, request/spec identity and original input bytes were equal before and after execution. The receipt contains the SHA256 of every included weight/config/tokenizer file and the implementation/runtime identity.
- Actual provider: MPS. Adapter input: 960 × 600. Input-to-frame transform: `(0.1, 0, 0.85, 1)`.
- Four person hypotheses were returned. Every raw input-space box maps exactly once to its legacy full-frame box. The overlay was opened and inspected: the three foreground boxes align with visible people; the distant low-confidence box remains an unreviewed hypothesis.
- This one call took 4.866 seconds including pipeline setup; the facade's measured total was 4813.558 ms. Component timings and cache state remain null. These measurements are not steady-state throughput claims.
- Receipt: `actual-smoke.json`; overlay: `actual-smoke-overlay.jpg`; unedited output including the upstream Transformers deprecation warning: `actual-smoke.log`.

The image is attributed to NVIDIA, PhysicalAI-SmartSpaces, CC-BY-4.0, repository revision `2cbe9563cbe9f47f846e5c871ee994572bbbc60e`. Input and script hashes are in the receipt. This is execution/identity/geometry evidence, not representative accuracy evidence. The new facade's native OCR, RT-DETR and SSDLite routes have deterministic integration coverage; no new learned/native calls for those routes are claimed by this smoke. YOLOX and Paddle remain isolated probes and are not selectable through this slice.
