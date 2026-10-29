# Candidate adapter onboarding notes · 2026-10-28

The original checks below guided implementation. They do not by themselves
register a callable adapter, establish local performance, or approve distribution.

## YOLOX integration update

Source `f0d1c365f956d3f57e11686ab58a1f7aa07a4595b2cb3f0b481a733a6a1451fb`
integrates the pinned YOLOX-s ONNX CPU adapter and an explicit reviewed installer.
The actual isolated API installation downloaded the official files, verified
their exact hashes and ran a generated-black-image inference. Installation and
execution readiness remain separate from accuracy. See
`artifacts/provisioning/installation-f0d1.json`.

The production adapter matched all 30 retained Warehouse_016 predictions from
the earlier official-code probe. Published synthetic labels remain unreviewed;
the unchanged 52.7% recall fails the declared 80% diagnostic target. This verifies
implementation parity, not warehouse suitability or a new independent holdout.
See `artifacts/provisioning/adapter-parity-f0d1.json`.

Code and weight license attribution retain their separate scope notes in the
installation plan. The app bundles adapted Apache-licensed source and its notice,
but no downloaded weights. The later `2f08` [aggregate report](../artifacts/runtime-validation-2f08.json) records actual packaged inference and native installation/build checks, with the final box-edit check explicitly incomplete after screen capture failed.

## Original candidate checks

* The official [SAM 3 repository](https://github.com/facebookresearch/sam3)
  specifies a CUDA-compatible GPU prerequisite. Its
  [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE)
  covers code and weights under custom terms. Local Mac compatibility is not
  established by those instructions. An actual supported-hardware smoke test,
  weight access and license review remain prerequisites.
* The official [YOLOX repository](https://github.com/Megvii-BaseDetection/YOLOX)
  offers a PyTorch implementation, published checkpoints and ONNX deployment.
  Its [repository license](https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE)
  is Apache-2.0. Pinning a concrete checkpoint, retaining its provenance and
  testing the chosen Mac execution path remain required; no performance result
  is inferred from the upstream benchmark.
* PaddleOCR publishes an [Apple silicon usage guide](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.html)
  and [installation documentation](https://www.paddleocr.ai/main/en/version3.x/installation.html).
  This supplies an official starting point for an OCR alternative. The exact
  engine/model pair, wheel compatibility, license, local inference and project
  label benchmark still need validation before selection.

Keep other prospective adapters explicitly unsupported in the current catalog until
implementation exists. Installing an adapter makes it eligible for a bounded
validation experiment; only measured evidence can establish readiness and
project-specific suitability.
