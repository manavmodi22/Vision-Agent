# Data and model provenance

Reference Mac: Apple M4 Pro, 48 GB unified memory. Downloaded public data is outside
Git under `~/Library/Application Support/VisionApp/datasets/`.

## NVIDIA sample

Source: [NVIDIA PhysicalAI-SmartSpaces](https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces),
revision `2cbe9563cbe9f47f846e5c871ee994572bbbc60e`, CC-BY-4.0.
Attribution: NVIDIA Physical AI Smart Spaces, Wang et al. (2026),
*Physical AI Smart Spaces: A large-scale benchmark for multi-camera 3D perception
in smart spaces*. Upstream README, per-file URLs and SHA256 digests are retained.
`scripts/prepare_nvidia.py` reproduces acquisition, frame extraction and projects.

* 30 frames: `MTMC_Tracking_2025/val/Warehouse_015/videos/Camera_01.mp4`.
  **Synthetic** Omniverse imagery. Published ground truth is filtered to person
  and forklift, clipped and normalized. App annotations remain unreviewed. The
  standalone benchmark trusts published labels and does not approve deployment.
* 20 frames: `MTMC_Tracking_2026/test/Warehouse_026/videos/Camera_0000.mp4`.
  **Real warehouse footage**. Ground truth is withheld upstream. Empty,
  unreviewed labels; no scored accuracy claim.
* Original geometric fixtures are **synthetic software tests**, separate from
  both NVIDIA projects. The fixture detector cannot run on ordinary projects.

These samples do not validate damage judgements, pallet counts or barcode
correctness. Correlated frames from one synthetic camera are not an independent
warehouse deployment test. No customer imagery was supplied or represented.

An additional fixed comparison uses 30 frames from 2025 `Warehouse_016/Camera_01`,
with 112 published person boxes. Source file hashes match the pinned repository's
LFS hashes. This source scene differs from Warehouse_015 used in prior work;
frames within it remain correlated. The same confidence 0.15, IoU 0.5 and 80%
recall target were recorded before running any model. App annotations were not
created or marked reviewed by this standalone benchmark.

| Model | Precision | Recall | Count MAE | Recall gate |
| --- | ---: | ---: | ---: | --- |
| OWLv2 | 50.9% | 72.3% | 1.70 | Failed |
| Pretrained RT-DETRv2 R18 | 12.4% | 75.9% | 19.03 | Failed |
| Isolated YOLOX-s ONNX | 37.8% | 52.7% | 1.73 | Failed |

Humanoid robots are separate upstream classes and remain negatives. Confusing
them with people is one observed failure, not a reason to change ground truth.
Scores are model-specific, so a common confidence threshold is a reproducible
baseline rather than each model's best operating point. See
`artifacts/scene-holdout/REPORT.md` for exact identities, predictions, failure
analysis and limitations. YOLOX is still an isolated probe, not a registered app
adapter. After these results have been inspected, this set is validation data;
future tuning still needs a separate untouched acceptance set.

## Models and server

* OWLv2: official `google/owlv2-base-patch16-ensemble`, revision
  `cfd3195ba4ea9592eec887ded089f4c08eff231d`, Apache-2.0 declared by the official
  [model card](https://huggingface.co/google/owlv2-base-patch16-ensemble).
  SafeTensors snapshot in app `models/owlv2-base-patch16`; actual MPS inference
  verified. Inference never silently downloads or substitutes a model.
* Planner: official `Qwen/Qwen3-14B-GGUF`, Q4_K_M, Apache-2.0, served locally as
  `visionapp-planner`. Revision `530227a7d994db8eca5ab5ced2fb692b614357fd`;
  GGUF SHA256 `500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0`.
  It is the provisional selection for full validation after a paired difficult
  subset. See [model selection and measured limits](planner-selection.md).
  Historical reports used Nemotron 3 Nano 4B and retain that attribution.
  Neither cached planner's weights are included in the application bundle.
* llama.cpp: official macOS arm64 release `b11963`; archive SHA256
  `b11dd41563b07b250841b4742e1a6e9675b34f82c7c7486a65c958f795b99ea3`.
  LM Studio CLI was present but its app/daemon was unavailable. The interchangeable
  server exposes a local compatible API; app and agent do not depend on its brand.
* Apple Vision: system OCR/barcode framework. Actual OCR smoke test verified.
* Custom training: pretrained RT-DETRv2 R18 from `PekingU/rtdetr_v2_r18vd`,
  revision `5650961749fa93567c0d46fc7f43ea4f9e914107`, Apache-2.0. Actual MPS
  training, SafeTensors save/reload and holdout inference are verified. Manifests
  retain base-weight provenance, class mappings and dataset hashes. Existing
  SSDLite checkpoints remain compatible; scratch SSDLite is not the default.
  See [training design and limits](training-design.md). Execution does not
  establish useful detector quality or approve deployment.

## Measured baseline

`artifacts/nvidia-benchmark/`: 30 frames; person/forklift; confidence 0.15; IoU 0.5.

| Metric | Result |
|---|---:|
| Precision | 0.8591 |
| Recall | 0.3918 |
| Count MAE per image | 29.0667 |
| Recall target | 0.80 — FAILED |
| Total elapsed | 41.59 seconds |

Runtime includes initialization, not steady-state camera FPS. Exact frames,
failures and hashes are saved. No app deployment approval was created. Useful
specialization still needs representative reviewed labels and a diverse holdout.
