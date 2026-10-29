# Common adapter boundary — design audit, not an implementation

Keep current graph types and old results working. Add one internal inference facade with a typed identity/timing envelope, wrap existing detectors and Apple Vision first, and only then register a validated new adapter. The YOLOX and Paddle artifacts prove isolated execution, not application integration or permission to bundle their runtimes.

## What exists and what the wrapper must preserve

- `engine/models/__init__.py::detect(image, model, classes, min_conf)` dispatches to OWLv2, RT-DETRv2, local RT-DETR/SSDLite descendants, or the explicit synthetic fixture. All return `list[Detection]`: normalized top-left xyxy boxes, label, required confidence. Closed models reject unsupported classes; OWLv2 accepts prompts. Never map forklift/pallet to a COCO substitute.
- OWLv2 and RT-DETR load only local snapshots, choose MPS when available and otherwise CPU, and cache by paths/file timestamps. Exact future identities require content-bound cache keys, not mtime as identity. Keep existing device choice semantics visible in evidence; no retry with a different model.
- `engine/blocks/reading.py::read_native` serializes a temporary PNG and invokes the configured app with a 30-second timeout. It returns only strings. The Swift implementation has recognition observations, confidence and geometry available, but the current wire contract discards them. Missing geometry/confidence must remain absent until an actual bridge change exposes it.
- `engine/runtime/executor.py` maps local detector boxes through `ImageValue.transform` once to original-frame coordinates. The same transform must map each text-polygon vertex. Adapters must return coordinates relative to **their own input image**, never apply project crop/zone transforms.
- `FrameResult.texts` currently deduplicates text; preserve that legacy projection. Rich observations should retain duplicates and ordering. `match` stays a separate deterministic block; expected text must never become an OCR prompt, lexicon, or post-correction hint.
- The narrow reading identity fix has now landed: `engine/blocks/reading_identity.py` binds native bridge bytes, OS/kernel/architecture and `apple-vision-en-us-v2`; `eval.spec_hash` includes it for OCR/barcode only. Native request language is now explicitly en-US. Actual native Cyrillic/Latin confusion remains an error; neither the adapter nor evaluator may transliterate it away.

## Concrete interface proposal

New neutral output DTOs belong in `spec/inference.py`; image handles and worker controls stay in `engine/adapters/`. Use `Contract` validation and bounded lists, finite numbers, maximum text length and total output bytes.

```python
# Three discriminated request variants, not an untyped options dictionary.
DetectionRequest(task='detection', model_id: str, classes: list[str], min_conf: float)
OcrRequest(task='ocr', model_id: str, languages: list[str])
BarcodeRequest(task='barcode', model_id: str)

# Engine-local API; this is a proposal, not importable code.
def run_inference(
    image: PIL.Image.Image, request: InferenceRequest, *,
    expected_identity_hash: str | None,
    deadline_monotonic_s: float | None,
    cancelled: threading.Event | None,
) -> InferenceResult: ...
```

A separate `resolve_execution_identity(request)` resolves and verifies local artifacts before compile/preview/evaluation; it does not run a learned model. `run_inference` must reject a changed identity, unavailable task, unsupported language/class or expired request. The coded registry maps IDs to implementations. Model IDs are never import names, executable paths, download URLs or user-supplied code.

| DTO / field | Exact proposed shape and semantics |
|---|---|
| `InferenceResult.schema_version` | Literal `1` |
| `task` | `detection`, `ocr` or `barcode` |
| `input_size` | `(width:int, height:int)`; positive and within existing image limits |
| `input_pixels_sha256` | Hash of canonical RGB dimensions/mode/pixels supplied to this adapter; separate from source-file hash |
| `detections` | `list[DetectionObservation]`, empty for readers |
| `readings` | `list[TextObservation]`, empty for detectors |
| `identity` | `ExecutionIdentity` below; returned identity must equal the engine-resolved identity |
| `timing` | `InferenceTiming` below |
| `warnings` | Bounded `list[str]`; never used to disguise partial success |
| `DetectionObservation` | `label:str`, `confidence:float[0,1]`, `box:xyxy`, `polygon:list[(float,float)]|None`; zone remains executor-owned |
| `TextObservation` | `text:str`, `kind:ocr|barcode`, `confidence:float[0,1]|None`, `box:xyxy|None`, `polygon:list[(float,float)]|None`, `symbology:str|None` |
| Geometry | Top-left origin, finite normalized coordinates in `[0,1]`. Positive-area boxes/polygons. Unknown geometry is null; do not invent word boxes from a whole-frame result. If a polygon exists, its envelope can supply the box. |
| `ExecutionIdentity` | `capability_id`, `model_id`, `adapter_id`, `identity_scope:local_artifacts_verified|system_framework_versioned`, `artifact_hashes:dict[relative_name,sha256]`, `adapter_code_sha256`, `runtime_manifest_sha256`, `system_identity:dict[str,str]`, `provider:str`, `config_sha256`, `identity_hash` |
| `InferenceTiming` | `total_ms:float>=0`, `startup_ms:float|None`, `load_ms:float|None`, `preprocess_ms:float|None`, `inference_ms:float|None`, `postprocess_ms:float|None`, `transport_ms:float|None`, `model_cached:bool` |

Null timing means unmeasured, not zero. Legacy wrappers initially measure only total time and known startup time. MPS component timing must synchronize the device or remain unreported; wall time around asynchronous submission is not inference time. Detection/recognition confidence is raw model output, not a calibrated probability. Do not return a fabricated confidence of 1 for Apple Vision's current string-only wire response.

Persist this envelope through additive `FrameResult.inferences=[]` entries keyed by block ID (engine-assigned), with a documented compatible schema addition. Keep `detections`, `texts`, counts, events and graph ports unchanged. These entries are evidence, not new graph-output ports or approval objects. Older records decode with empty evidence; do not fabricate identities for historical runs.

## Identity and lifecycle details

For learned models, include every consumed weight/config/tokenizer/dictionary/preprocessor file and the adapter's preprocessing/decoding implementation. Local fine-tuned models also bind their manifest and vocabulary. Hash content at registration/load; use immutable content-addressed installations and cache by verified identity. Stat checks can trigger revalidation but never substitute for a content identity. Fail when artifacts change between resolution and load; do not keep a model loaded under the old name while recording a new file hash.

Apple Vision's hidden system model weights are not independently verified. Its scope remains `system_framework_versioned`: app binary content, macOS/kernel/build, request policy/revision and options. Do not describe an OS version as a verified weight hash. Extend the newly added helper when native request revisions become observable; reuse it in platform snapshots rather than maintaining parallel identity definitions.

Execution provider and effective configuration belong to the identity. Include OWLv2 class prompts, confidence/NMS choices, OCR language and segmentation settings. A new identity invalidates evaluation and deployment evidence. Run-result metadata does not independently grant deployment; existing review, score and approval gates remain authoritative.

The current executor is synchronous. Keep that boundary; pass cancellation/deadline into runners. An in-process Torch call cannot honestly promise hard cancellation mid-kernel. Check before/after and discard late results. A worker can be terminated on timeout/cancel, with bounded stderr/stdout and cleanup; never persist late events. Queue limits and disposal belong to the existing run/job lifecycle rather than a new scheduler.

## Per-candidate planner contract, coordinated with agent_harness

Keep the new `PlanningModelOption` identifiers and `detections/v1` / `texts/v1` projections stable. It remains lightweight discovery: installed prerequisites can be `unchecked` and eligible for a bounded experiment; that is distinct from inference-proven readiness. An exact execution identity is resolved later and saved with the plan/evidence.

The current planner correctly offers only `model.apple-vision` for reading and verifies that selection; its executor still routes readers directly to the native bridge. Do not expose Paddle as selectable before runtime routing exists. Later, add `ReadingParams.model='apple-vision'` as a backward-compatible default, and a corresponding barcode model field/default. Update compiler, executor, plan required-capability calculation and selector validation in the same release. Existing saved readers preserve native behavior.

Proposed new IDs only after implementation/review: `model.yolox-s-onnx-coco` / adapter `yolox-onnx` (closed COCO detection); `model.ppocrv5-mobile-en` / adapter `paddleocr-cpu` (English OCR only, not barcode). The descriptor supplies task types/vocabulary/languages and runtime readiness to both catalog and planner. Unknown or unsupported adapters stay blocked. No download/install is triggered by a plan choice. Candidate comparison still requires the same task, class/zone/event scope, metric/target and frozen dataset; a faster closed detector is not a substitute for an unsupported requested class.

## Smallest implementation sequence and ownership

| Step | Proposed exact files / owner | Required proof |
|---|---|---|
| 1. Wrap current behavior | Core: new `spec/inference.py`, `engine/adapters/contracts.py`, `engine/adapters/registry.py`, `engine/adapters/legacy.py`; existing `engine/models/{owlv2,rtdetr,ssdlite}.py`, `engine/eval/hashes.py`, `engine/runtime/{executor,values}.py`, additive `spec/models.py` | Same detections/text/events; crop+resize mapping only once; null unknown evidence; stale identity rejection; no detector-class remapping |
| 2. Enrich native reading without breaking old callers | Native: `app/Sources/VisionApp/VisionBridge.swift`; core: `engine/blocks/reading.py`, `engine/blocks/reading_identity.py` | Keep legacy `--analyze-image` output; add an explicitly versioned rich protocol so old strict Python parsers do not receive unexpected fields. Validate coordinate-origin conversion, actual confidence, policy and literal text. |
| 3. Register YOLOX | Core: new `engine/adapters/yolox.py`; registry/model inventory/compiler; root: optional dependency and packaging changes | Pinned weights/code, closed vocabulary, official preprocessing/NMS equivalence, offline failure, reviewed common-class evaluation, relocated signed runtime check |
| 4. Optional Paddle worker | Core: new `engine/adapters/workers/paddle_ocr.py` and bounded worker transport; root: registered optional-runtime manifest/install path | Image-only licensed dependency resolution; local model/config identity; finite text/polygons; no expected answer; cancellation and no network/fallback; clean startup and cache disposal |
| 5. Reader selection and presentation | Core: `engine/blocks/{params,registry}.py`, compiler/executor; harness: `spec/planning.py`, `engine/platform/{planning_options,store}.py`, `agent/model_selection.py`, decision/selection schemas; native: result DTO/overlays | Saved model choice matches actual adapter, default native compatibility, capability disappearance/revision change fails clearly, all alternatives evaluated consistently |

The next implementation slice should stop after step 1: the neutral DTO, registry/facade and wrappers around the three existing backend families, with additive result evidence and identity invalidation tests. It requires **zero new production dependencies, models or planner choices**. Do not combine YOLOX/Paddle promotion or the rich native protocol with that first slice. Its acceptance check is unchanged existing predictions/events plus one real existing-adapter preview, verified input-space coordinates, explicit null unknown fields and rejection after an artifact identity changes.

Root owns production dependency/lock and package scripts throughout. No new adapters, fields or dependencies in this table have been implemented by this design artifact. The separately authorized native reading-identity fix is the only production change in this audit turn.

## Runtime/dependency strategy

Keep the existing Torch/Transformers adapters and Apple Vision in their current bundle initially. YOLOX's isolated ONNX probe already worked with the app's numpy/OpenCV/Pillow versions; consider a separate optional `vision-onnx` extra with ONNX Runtime after a complete lock and native-library relocation/signing check. Default inclusion is not justified by a successful developer venv alone.

**Do not merge the full Paddle probe environment into the app.** Its tested versions include numpy 2.3.5, OpenCV contrib 4.10.0.84 and Pillow 13, versus the app's numpy 2.5.4, OpenCV headless 4.14 and Pillow<13 constraint. Use an explicitly registered optional environment and a warm image-only worker after dependency review. The first probe import took 47.4 seconds, so a fresh Python process per frame is unsuitable. Worker startup cost, deadline, maximum one in-flight request and memory/disk limits must be visible. Transfer an engine-owned image file initially; do not add another shared-memory protocol before measurements justify it.

The package/license issue is substantive, not hypothetical. The 71-package probe includes LGPL-licensed components and PDF readers unrelated to image OCR; see `../ocr/RUNTIME_LICENSE_NOTES.md`. A separate process avoids version conflicts but **does not remove distribution obligations**. First investigate direct image detection/recognition with a reduced dependency set and no PDF/hub/download modules; prove the reduced path with the same fixtures. Do not remove dependencies with `--no-deps` and call the result supported without testing imports/execution. An optional externally installed worker is an integration choice, not a license exemption. Keep all current model/code and transitive-runtime license scopes explicit in catalog/install records.
