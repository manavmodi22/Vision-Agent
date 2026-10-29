# Proposed direct OCR runtime contract

This is an isolated prototype contract, not production registration or a quality gate.

- Model ID: `ppocr-v5-mobile-en`; adapter ID: `paddle-ocr-cpu`.
- Task: OCR only. English recognizer vocabulary is the pinned 436-entry dictionary in its config, plus CTC blank and space. No language correction, case folding, transliteration, expected-text input, barcode decoding, or substitute model.
- Input: one local raster image, at most 24 million pixels and 8192 pixels per side. The prototype reads RGB pixels with Pillow and converts to BGR; it does not apply EXIF orientation. Production should pass already-oriented adapter input pixels so geometry maps once.
- Output: raw text, mean selected CTC token score, separate detector mask score, 4-point pixel quadrilateral in input coordinates, measured detection/recognition/total timings. Scores are model scores, not calibrated correctness probabilities. Upstream top-to-bottom/left-to-right ordering, with a 10-pixel row tolerance, is retained.
- Execution: CPU only, two configured inference/OpenCV threads, recognition batch size one, max-side-960 detector preprocessing, at most 128 text regions. No model download. Missing or changed files reject before predictor construction. Outer batch process has a 180-second hard timeout and macOS `deny network*` sandbox, checked with an actual denied socket before and after inference.

Expected installed model root contains two directories with the exact upstream names:

```
PP-OCRv5_mobile_det/{config.json,inference.json,inference.pdiparams}
en_PP-OCRv5_mobile_rec/{config.json,inference.json,inference.pdiparams}
```

All six mandatory hashes are in `direct_ocr.PINNED_FILES`; the original download receipt also binds model cards/YAML and official revision URLs. Detector revision is `0d63e78e2b680928f6b1747d76a08db6e645efb7`; recognizer revision is `267c36e24c331595590fe7bd72bde2436fd286f2`. Model-card Apache-2.0 declarations are publisher evidence, not a claim of an independent asset-specific legal audit.

The future provisioning manifest should bind model files, the exact Python runtime distribution, every wheel/hash, the locally built image-only OpenCV wheel, adapter source hashes, preprocessing policy version, platform/architecture, and the fixed smoke request. Dependency metadata and actual binary linkage must be separate from the model license. A healthy install means the declared adapter smoke ran; it does not establish task accuracy or independent evaluation evidence.

The smallest production shape is an optional isolated runtime and an app-owned serial worker, not Paddle in the main application environment. A worker should be keyed by model/runtime/source identity, process one request at a time, bound input/output and lifetime, expire while idle, and be killed on timeout/cancellation. A dependency/model/source change must invalidate its health receipt and restart the worker. Never fall back to Apple OCR when Paddle fails or substitute Paddle when Apple was selected.

The prototype venv is tied to this host's existing CPython installation. The custom OpenCV wheel is CPython3.12/macOS-arm64-specific; its build uses the local Apple SDK. A redistributable runtime needs its own pinned Python, native dependency/notices inventory, signing and relocation test. Neither moving this venv nor the `macosx_11_0` wheel tag proves support on older macOS releases.

## API and batch invocation

Use the isolated Python, add this artifact directory to `sys.path`, then:

```python
from direct_ocr import DirectOCR

reader = DirectOCR()
result = reader.read(image_path)
```

For a bounded offline batch, write a JSON array of image-path strings **only**. Do not include expected transcripts. The runner generates path/hash identities, launches its child under OS network denial and returns a JSON report:

```sh
.venv/bin/python artifacts/adapter-probes/ocr-minimal/run_offline.py \
  --paths /absolute/path/image-paths.json \
  --output /absolute/path/raw-ocr-output.json
```

The parent launcher uses only the Python standard library. Its child always uses `.visionapp/adapter-probes/ocr-minimal/venv/bin/python`. Results include observations, timings, package versions, source hashes and loaded native libraries. Expected transcripts may be read by a separate scorer only after the child exits. Root owns the separate TextOCR diagnostic; it has not been run by this probe.
