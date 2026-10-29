# Installed Paddle probe: runtime license findings

This is a metadata/source-notice audit of the **actual isolated 71-package environment**, not a legal conclusion or a complete distributable bill of materials. Paddle model/code Apache-2.0 does not describe the entire runtime. `cpu-dependency-licenses.json` records versions, declared licenses and SHA256s of installed notice files.

| Installed component | Observed notice / dependency edge | Consequence for the proposal |
|---|---|---|
| `python-bidi==0.6.12` | LGPL classifier; ships `COPYING.LESSER` LGPLv3 plus GPLv3 text incorporated by that license. Pulled by PaddleX `ocr-core`. | Not a permissive-only dependency. Do not misclassify it as standalone GPL just because `COPYING` exists. Assess whether English-only inference needs it. |
| `crc32c==2.9.post0` | Declares LGPL-2.1-or-later; its installed LICENSE is LGPL2.1. Pulled by `bce-python-sdk`, which is part of the broader stack. | Investigate excluding network/storage SDKs from local-image inference; no silent license-policy bypass. |
| `shapely==2.2.0` | Python package BSD-3-Clause, but wheel includes `LICENSE_GEOS` marked LGPLv2.1. PaddleX `ocr-core` requires Shapely. | Top-level package label is incomplete for the binary dependency. Determine whether its geometry operations are essential before selecting a replacement or packaging it. |
| `opencv-contrib-python==4.10.0.84` | Apache2 top-level; installed `LICENSE-3RD-PARTY.txt` includes LGPL text. Required by PaddleX `ocr-core`. | Inspect the exact included native components; do not declare the complete wheel Apache-only. A headless/minimal image build would need its own validation and notices. |
| `pypdfium2==5.14.0` | Metadata says BSD-3-Clause/Apache-2.0/dependency licenses. 18 installed license files include PDFium, FreeType, ICU, JPEG and other notices. PaddleX `ocr-core` pulls it even for this image-only probe. | Avoid PDF support in a minimal image adapter where possible. Some notices mention GPL with exceptions or alternative terms; those mentions alone do not establish that the complete package is GPL. Review actual bundled components and applicable terms. |
| `certifi==2026.10.23`, `tqdm==4.70.1` | MPL-2.0; MPL-2.0 AND MIT respectively. | Also distinguish these from a uniformly MIT/Apache runtime. |

The saved dependency edges confirm that selecting only PaddleOCR's `ocr-core` extra does **not** remove PDF or all weak-copyleft dependencies. Optional isolation prevents app ABI/version conflicts; it is not a waiver of redistribution obligations. Do not bundle all 71 packages by default or relabel them collectively permissive.

Next bounded step, after authorization: inspect a direct image-only Paddle detector/recognizer path that avoids full PaddleX orchestration and automatic model-host tooling, resolve its actual dependency graph, retain required notices, then repeat offline literal/geometry tests. No reduced runtime has been built or proven yet. Existing installed probe files are retained as evidence; no package was uninstalled or changed during this audit.
