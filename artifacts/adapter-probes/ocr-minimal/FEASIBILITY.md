# Direct image-only PP-OCRv5 CPU proof

**Feasible on this Apple-silicon host; not production-registered.** The pinned detector and English recognizer ran through `paddle.inference` with no PaddleOCR/PaddleX orchestration. All five images reproduced the official probe's text and pixel quadrilaterals. The four synthetic literals preserved case and leading zeros, with identical recognition scores. The unlabelled public crop retained its four hypotheses; recognition-score changes reached **0.00055334** after replacing the image library. This is implementation-parity evidence, not representative OCR accuracy.

| Input | Direct text | Direct image work | Compared with official retained probe |
|---|---|---:|---|
| Exact fixture | `ABC-990` | 278.4 ms | Text, score and polygon identical |
| Substring fixture | `XABC-990Y` | 231.4 ms | Text, score and polygon identical |
| Leading zeros | `001234567890` | 164.9 ms | Text, score and polygon identical |
| Mixed case | `AbC-009x` | 167.1 ms | Text, score and polygon identical |
| Public warehouse crop | `ENTP0343`, `BLI`, `FMP012 15`, `W0` | 547.1 ms | Text/polygons identical; small score differences; no transcript GT |

`image-only-result.json` is the final raw run; `parity.json` scores it against the retained official output **after inference**. `sampling-comparison.json` shows the changed OpenCV build alters a few crop/resize tensor elements on slanted regions; no text normalization or answer-directed correction was added. Inference inputs contain only image path, ID and SHA256. No reviewed annotations or user-project files were created or changed. The public crop provenance remains the original NVIDIA CC-BY4 record in `../ocr/cpu-public-source-provenance.json`.

## Actual bounds and checks

The process was launched with macOS `sandbox-exec` `(deny network*)`; actual socket attempts failed with EPERM before and after inference. The parent enforces a 180-second subprocess timeout. CPU/OpenCV threads are configured to two, GPU is disabled, recognition batch size is one, input size is bounded, and excessive detected regions reject. Runtime rejects altered/missing pinned files, nonfinite model output and unsupported shapes. No PaddleX, PaddleOCR, Shapely, PDFium, bidi or cloud SDK import occurred.

Fourteen deterministic checks passed, covering CTC blank/repetition behavior, literal case/zeros, finite output/shape checks, geometry and associated scores, resize/crop bounds, artifact mutation/missing files, and refusal to accept expected-answer records in the batch path. Scoped Ruff and installed dependency consistency checks pass. This is not an exhaustive robustness or representative recognition evaluation.

Final fresh-process import was **1174.7 ms**, predictor initialization **119.4 ms**, and five-image execution including those steps **2899.0 ms**. Earlier fresh processes ranged from about 1.0 to 2.7 seconds for import, with already-used filesystem caches. These are host observations, not a controlled throughput benchmark. A bounded serial worker avoids paying import/init for every image; see `PROPOSED_RUNTIME.md`.

## Reduced runtime and provenance

The final environment has **18 distributions**, about **503 MiB allocated / 561,668,320 logical bytes**. The complete new work directory, including build tools, source archive, source tree, objects and wheel, is about **975 MiB**, below the requested bound. Existing model files and the original 71-package probe remain untouched. No main environment, production source, package, app or catalog was modified.

`requirements.lock`, installation receipts, `dependency-notices.json`, and `native-library-inventory.json` capture exact installed versions, downloaded-wheel hashes, installed notice hashes and native linkage. The direct algorithms are adapted from official [PaddleX3.7.2 commit ffb6490](https://github.com/PaddlePaddle/PaddleX/tree/ffb64904d23708863ff5b8da312a5cbd52a7f462); downloaded source bytes match the previously installed official probe. Apache license and attribution are retained.

The initially selected stock `opencv-python-headless==4.10.0.84` was **not suitable for a permissive-only claim**: its loaded FFmpeg binary reports GPL version3 or later, with `--enable-gpl` and x264/x265 enabled. That evidence and the successful first inference are retained, rather than overwritten or relabeled. It was removed **only from this new isolated environment**.

The replacement is a local 3,078,501-byte wheel built from official [OpenCV4.10.0 commit71d3237](https://github.com/opencv/opencv/tree/71d3237a093b60a27601c20e9ee6c3e52154e8b1), with only `core,imgproc,python3`. Wheel SHA256 is `05f2fabe8c5c67c7ff665fad7421105764292453c1106d9a1b9efed6d06d1742`. Its actual linkage is system zlib, Accelerate, libSystem and libc++; `VideoCapture`, `imread`, and `imshow` are absent. Final loaded-library evidence contains no FFmpeg/x264/x265/fontconfig/FreeType/PDFium/GEOS. Apache OpenCV, BSD Carotene and Flatbuffers notices accompany the wheel. CMake's first build inherited the enclosing repository's git label; that metadata was corrected explicitly to the pinned OpenCV revision, and both earlier evidence and the final rerun are retained.

**The complete runtime is still not uniformly permissive.** Certifi is MPL2; setuptools includes separately licensed vendored components. Paddle's wheel contains native GCC/Fortran/quadmath files beyond its top-level Apache notice. Those files were not loaded by this measured inference, which used system Accelerate, but their presence still matters if the wheel is redistributed. The exact native/notice mapping needs review; do not assign NumPy's GCC-runtime exception notice to a different Paddle binary by assumption. The package-level license inventory is not a legal conclusion or a complete distributable SBOM. Optional isolation does not remove license obligations.

## Handoff

The reusable no-answer API and offline batch command are in `PROPOSED_RUNTIME.md`; `proposed-model-manifest.json` binds all six required model/config files and their official URLs. The independently frozen 100-crop TextOCR diagnostic is owned by root and was not run here. Production registration, worker lifecycle, signed/relocatable Python distribution, installer receipts and health integration remain a subsequent reviewed slice. This host-specific venv is not a portable deliverable.
