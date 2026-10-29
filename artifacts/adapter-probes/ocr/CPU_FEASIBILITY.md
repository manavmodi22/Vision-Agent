# PP-OCRv5 mobile CPU feasibility — actual isolated run

**Succeeded on this Apple Silicon Mac, with network access denied and two CPU threads.** Four synthetic literal fixtures were preserved exactly. One unlabelled real warehouse label crop also produced text, polygons and native recognition scores. This is an import/inference and literal-preservation smoke test, not a representative accuracy benchmark or a production adapter.

No production source, dependency lock, native app, server, model catalog, project annotation or deployment approval was changed. The complete isolated environment and models occupy approximately **832 MiB**, below the requested approximately 2 GB cap. No GPU or LLM inference was used.

## Exact inputs and observed output

| Input | Raw recognized text | Native recognition score | Inference observation |
|---|---|---:|---:|
| Existing exact-match fixture | `ABC-990` | 0.999969 | 294.6 ms |
| Existing substring-only fixture | `XABC-990Y` | 0.999905 | 238.8 ms |
| Original generated leading-zero fixture | `001234567890` | 0.999880 | 173.0 ms |
| Original generated mixed-case fixture | `AbC-009x` | 0.999856 | 171.2 ms |
| Real public warehouse crop | `ENTP0343`, `BLI`, `FMP012 15`, `W0` | 0.988930, 0.231220, 0.895058, 0.235610 | 560.2 ms |

Case, punctuation and leading zeros survived unchanged on these four clean synthetic images. The substring remains different from `ABC-990`; no expected-answer hint, whitelist, post-correction or case folding was supplied to OCR. Scores are the model's raw recognition outputs, **not calibrated probabilities of correctness**.

The real crop is derived from NVIDIA PhysicalAI-SmartSpaces Warehouse_026, revision `2cbe9563cbe9f47f846e5c871ee994572bbbc60e`, CC-BY-4.0 with NVIDIA attribution. It has **no transcript ground truth**. Its overlay was visually inspected: some reported regions cover barcode-like patterns and yield low-confidence text. These outputs remain hypotheses; they do not decode barcode payloads or establish label-reading accuracy. Full source provenance and crop coordinates are retained; every input remains `reviewed=false`.

## Runtime and reproducibility

- Python 3.12.14, macOS 26.7.1 arm64. Paddle reports `device='cpu'`, CUDA compiled false. `cpu_threads=2`, BLAS/OpenMP/Accelerate thread caps two, MKLDNN disabled, recognition batch one; maximum detection side 960. Orientation/unwarping auxiliary models disabled. Recognition threshold zero preserves low-confidence failures for inspection.
- PaddleOCR 3.7.0, PaddleX 3.7.2, PaddlePaddle 3.2.1, numpy 2.3.5, OpenCV contrib 4.10.0.84, Pillow 13.0.0; 71 isolated distributions. The app environment was not used or upgraded. The installed package record hashes and license/notice file hashes are captured. `probe-requirements.lock` contains exact versions and accepted package hashes; install used `--require-hashes` and no retained package-download cache.
- Model directories contain only the pinned official detector and English recognizer files. Detector revision `0d63e78e2b680928f6b1747d76a08db6e645efb7`; recognizer revision `267c36e24c331595590fe7bd72bde2436fd286f2`. Weight SHA256s match the publisher's LFS digests; configuration/README Git blob identities were also checked. All ten downloaded files total 12,954,085 bytes. All model/config and input hashes were rechecked after inference.
- Detector weight SHA256: `afa1820cb16c1fd0dad589d0f8b389139061c1ef6d68019685fd07be997dda5b`.
- Recognizer weight SHA256: `3ec8a97ed6cefe8568d3e2ee90bb193299b566a7661aa4fd52d224b96b59f66b`.
- First imports in the fresh environment took **47.4 seconds**; model initialization then took **171.7 ms**. The table contains one inference observation per image with different dimensions, not repeated p50/p95 latency or a throughput claim. Import cost is material for a future worker design.
- The process ran under macOS `sandbox-exec` with `(deny network*)`. Model-source connectivity checks were disabled, local model directories were explicit, and a separate OS-level connection test returned EPERM. No implicit download or remote fallback was possible during this run. A 180-second process signal deadline was configured; the run completed normally.

The code and both official model cards declare Apache-2.0. Model README hashes, the saved upstream code license hash, dependency license metadata and installed license/notice hashes are recorded separately. This preserves source boundaries; it does not assign a license to this app or complete a distributable dependency audit. Sources: [detector](https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det/tree/0d63e78e2b680928f6b1747d76a08db6e645efb7), [English recognizer](https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec/tree/267c36e24c331595590fe7bd72bde2436fd286f2), [PaddleOCR license](https://github.com/PaddlePaddle/PaddleOCR/blob/dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf/LICENSE).

## Evidence and remaining work

- `cpu-feasibility.json`: raw text, polygons, confidence, timings, configuration, installed package record hashes and five passing smoke assertions.
- `cpu-inputs.json`: source hashes, synthetic/public provenance, exact synthetic strings, crop geometry; no fabricated review.
- `download-receipt.json`: verified model/config hashes and exact download sources.
- `cpu-dependency-licenses.json`, `cpu-installed.txt`, `probe-requirements.lock`, `install.log`: dependency evidence.
- `cpu-run.log`: complete run output including warnings. Paddle warned about multi-threaded OpenMP/OpenBLAS use; execution succeeded, but do not erase this warning when choosing future defaults.
- `cpu-*-overlay.png`: observed outputs; real-crop and mixed-case overlays visually inspected.
- `probe_cpu.py`: executable bounded probe; Ruff passes. `cpu-artifact-sha256.json` binds this evidence snapshot.

The earlier `RECOMMENDATION.md` and `pins.json` are retained as the pre-install research snapshot; this report supersedes their untested status **only for the two mobile models on the tested isolated CPU path**. VL/MLX and Tesseract remain research-only. No catalog capability is promoted by this artifact.

Next: follow the still-unexecuted `PROBE_PLAN.md` on licensed, frozen scene-disjoint data, compare the common text outputs against Apple Vision, and measure repeated warm/cold latency and packaged-worker startup. Cancellation and missing-model behavior need explicit adapter tests before production integration. No representative OCR score, deployment pass or native integration is claimed here.
