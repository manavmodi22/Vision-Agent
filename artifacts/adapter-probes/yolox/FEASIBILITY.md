# YOLOX-s ONNX: isolated Mac CPU feasibility

Status: **actual inference verified; production adapter not implemented or registered**. This is an isolated candidate probe, with no production dependency, catalog, model-selection, annotation, or approval changes. No LLM, MPS, or CoreML execution was used.

## Reproducible inputs and licenses

- Official code pinned to `6ddff4824372906469a7fae2dc3206c7aa4bbaee`; downloaded source file hashes are in `provenance.json`. Code license: [Apache-2.0 at that commit](https://github.com/Megvii-BaseDetection/YOLOX/blob/6ddff4824372906469a7fae2dc3206c7aa4bbaee/LICENSE). The upstream preprocessing and postprocessing implementation was inspected; postprocessing is imported from the pinned local file.
- Official [0.1.1rc0 release](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0), asset `yolox_s.onnx`, 35,858,002 bytes, SHA256 `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`. This is the model linked from the [official ONNX guide](https://github.com/Megvii-BaseDetection/YOLOX/blob/6ddff4824372906469a7fae2dc3206c7aa4bbaee/demo/ONNXRuntime/README.md). GitHub did not supply an asset digest; the SHA is computed locally. The repository code license is verified; the inspected release has no separate asset-specific license statement. Weight redistribution/license scope needs an explicit decision before packaging. The COCO-trained checkpoint does not confer rights over all training imagery.
- Runtime: Python 3.12.14, macOS 26.7.1 arm64; `onnxruntime==1.31.1` with **CPUExecutionProvider only**. Final probe reuses production versions of numpy 2.5.4, OpenCV headless 4.14.0.94 and Pillow 12.3.0. Isolated resolved versions and package-declared license metadata are in `requirements.lock` and `dependency-metadata.json`. [Official ONNX Runtime Python documentation](https://onnxruntime.ai/docs/get-started/with-python.html).
- NVIDIA PhysicalAI-SmartSpaces, revision `2cbe9563cbe9f47f846e5c871ee994572bbbc60e`, CC-BY-4.0, attribution NVIDIA. Actual source provenance, media SHA256s, frame numbers and annotation hash are embedded in `feasibility.json`. [Pinned dataset source](https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces/tree/2cbe9563cbe9f47f846e5c871ee994572bbbc60e). Real image: Warehouse_026; published synthetic person labels: Warehouse_015 / Camera_01. Existing labels were read without changing their unreviewed status.

## Observed results

| Check | Observed |
|---|---|
| Import/session | Success; input float32 `[1,3,640,640]`, output `[1,8400,85]`, finite outputs |
| Real unlabelled warehouse frame | 3 person predictions; overlay visually inspected; no accuracy claim |
| Unknown classes | `forklift` and `pallet` rejected before inference; no remapping |
| Published synthetic snapshot | 30 correlated frames, 1,543 person GT boxes; TP 904, FP 40, FN 639 |
| Person-only diagnostic | Precision 95.76%, recall 58.59%, count MAE 19.97; IoU 0.5 |
| Warm real-frame inference | Final aligned environment median 75.2ms over 5 calls, range 57.1–218.9ms, 4 CPU threads |
| Repeat after aligning dependencies | Identical real and all 30 synthetic frame predictions; original run retained separately |

The score threshold was 0.15; NMS IoU 0.45. The probe follows upstream class-agnostic NMS over all 80 COCO scores, then selects requested `person` results. These settings and this order must be fixed when comparing adapters. The first isolated environment measured a 39.5ms warm median; changing host load and environment make these observations unsuitable for an FPS promise. CPU inference feasibility is established; sustained capture throughput and thermal behavior are untested. The current recall would fail an 80% recall target on this synthetic snapshot.

The historic OWLv2 metric combined person and forklift, so **no cross-model ranking is claimed**. There is no real-scene labeled score here, no scene-disjoint holdout, and no evidence of forklift/pallet or custom-class support. Results are hypotheses for adapter selection, not a deployment approval.

## Proposed adapter contract (not implemented)

`detect_yolox(image: PIL.Image.Image, manifest: LocalModelManifest, classes: list[str], min_conf: float) -> list[Detection]`

- Suggested stable candidate ID `yolox-s-onnx-coco`; require a local immutable ONNX file and manifest SHA256, upstream commit/release, declared license scope, exact 80-class vocabulary, input/decode version and provider. No automatic network download or detector fallback.
- Validate requested classes against the closed vocabulary before loading. Reject unknown classes with supported-class guidance; never map forklift to truck or pallet to box. Validate finite normalized output boxes and scores.
- Convert app RGB images to BGR, preserve the official 640x640 top-left letterbox with padding114, bilinear resize, raw float32 CHW input; use stride8/16/32 decode and pinned NMS behavior. Cache one CPU session by weight/config identity, bounded to four intra-op threads and one inter-op thread.
- New optional runtime dependency: `onnxruntime==1.31.1` plus its transitive dependencies; reuse existing numpy/OpenCV/Pillow. The probe does not require installing the full YOLOX PyTorch training package or exporting checkpoints. Architecture-specific bundled wheel relocation/signing remains a separate packaging check.
- Installation state and smoke health remain distinct: a local valid ONNX file is installed; an identity-bound real inference receipt supports readiness only for the tested adapter/provider. This probe must not make the existing unsupported YOLO catalog slot callable.
- Fine-tuning is not demonstrated. The fixed COCO head must not be sold as custom warehouse classes.

Next verification gate: implement the bounded adapter after code review; settle checkpoint redistribution scope; score both candidates on exactly the same person-only scene-disjoint reviewed holdout with frozen settings; test cancellation and packaged ONNX Runtime on a relocated Mac bundle. No quality-target bypass.

## Artifacts and rerun

- `feasibility.json`: final detailed predictions, timings, source hashes and metrics.
- `feasibility-initial-env.json`: original run, retained as historical evidence.
- `real-person-overlay.jpg`: inspected real-image prediction overlay.
- `summary.json`: compact diagnostic output.
- `provenance.json`, `release.json`, `main-commit.json`: official source identities.
- `probe.py`: executable probe, Ruff-clean. Source/model/media/annotation hashes are checked before and after use. It writes artifacts only.

From the repository root, rerun with `.visionapp/adapter-probes/yolox/venv/bin/python artifacts/adapter-probes/yolox/probe.py`. The isolated venv and official model/source files reside in `.visionapp/adapter-probes/yolox`; no production dependencies were installed.
