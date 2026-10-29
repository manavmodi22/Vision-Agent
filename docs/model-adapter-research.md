# Candidate adapter onboarding notes · 2026-10-28

These checks guide upcoming implementation. They do not register a callable
adapter, establish local performance, or approve a model for distribution.

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

Keep prospective adapters explicitly unsupported in the current catalog until
implementation exists. Installing an adapter makes it eligible for a bounded
validation experiment; only measured evidence can establish readiness and
project-specific suitability.
