# Validation evidence

The current packaged-build record is [runtime-validation-final.json](runtime-validation-final.json).
It links to versioned reports and preserves failed attempts alongside successful
checks. The latest native workflow evidence is in
[agent-experience/adapter-release/](agent-experience/adapter-release/).

These are historical development observations on the reference Mac, not portable
test fixtures or general accuracy claims. Reports retain the original timestamps,
source hashes, local paths and hardware details. An absolute path in a report may
refer to a local input or cached model that is not included in this repository.

Source code, reproducibility scripts, small reports and review screenshots are
versioned. Downloaded model weights, full datasets, application state, built app
bundles, extracted package checks and archived experiment source copies remain
local and are excluded from Git. Model/data acquisition and provenance are
documented in [data-and-models.md](../docs/data-and-models.md).

Warehouse imagery in the validation screenshots and overlays comes from NVIDIA
PhysicalAI-SmartSpaces, licensed CC-BY-4.0. See the adjacent sample/probe provenance
records and [the upstream dataset](https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces).
Overlays and crops are derived views; they do not establish reviewed ground truth.
