# Proposed full-scene A0 case: bus destination display

Status: **prepared, visually inspected, not executed against the planner or a vision adapter**. The task and reference were frozen before any A0 decisions on this scene. No production source, app project, labels, review state or approval was changed.

Use the exact contents of `planner-prompt.txt` for both variants. Import only the selected variant's `scene.jpg` into a fresh project through the normal workspace import. Keep `manifest.json`, expected text, annotation geometry, prior reader outputs and the other variant out of the planner context.

The full scene is a 1024 × 768 photograph with a clear target but several plausible distractors: operator branding, a registration plate, another bus's route display and building text. The front display occupies a small portion of the image. The evaluator reference is route **43**, destination **PLYMOUTH SKI CENTRE**, supported by TextOCR annotations and inspection of the original photograph. Exact reference words and polygons are in the manifest; this is not human review of app annotations.

The counterpart is a genuine pixel degradation of the same complete scene: 128 × 96 Lanczos reduction, Gaussian blur with radius 0.6 at that size, then JPEG quality 25. It retains the bus scene but reduces the destination words to roughly 2.4–3 pixels high before blur. The prepared derivative was visually inspected; its destination text is not legible in that inspection. This is information loss in the supplied pixels, not a fabricated adapter error. There has been no adjustment based on reader or planner results.

| Variant | Ignored local input | SHA256 of file |
| --- | --- | --- |
| Original | `.visionapp/a0-investigation/cases/bus-destination-v1/original/scene.jpg` | `4fb978a9f3e17e86656caac0a9802d26296d9a2207a422969beb14ff11ee9837` |
| Degraded | `.visionapp/a0-investigation/cases/bus-destination-v1/degraded/scene.jpg` | `ad9df1ab3fdf7fb6139a8a3b0f5fc467ba30a3669c577dc33eb364abbd47b06f` |

The manifest records decoded RGB hashes because normal import can change file encoding without changing pixels. `prepare_case.py` shows every preparation operation and refuses to overwrite a frozen manifest.

The proposed positive trace must contain actual vision output and a subsequent materially different model-selected action supported by that observation, then a compiled and previewed draft whose final text and geometry pass the predeclared checks. A correct first attempt remains a valid result but alone does not demonstrate adaptation. The degraded case should request better input or stop with supported uncertainty when the destination cannot be recovered; an unexpectedly correct actual reading must be retained honestly. Run both with the same frozen runtime and prompt. Do not force an action sequence, a crop or a first failure.

Attribution: **Plymouth M53HOD**, Graham Richardson, [original Flickr landing page](https://www.flickr.com/photos/didbygraham/14796041516). The retained [official Open Images metadata](https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv) declares [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/). That declaration is retained in `manifest.json` and the existing `artifacts/reader-evaluation/textocr-manifest.json`; the individual Flickr licence has not been independently reverified. Images and the derivative remain in ignored local storage and are not redistributed by this repository. [TextOCR](https://textvqa.org/textocr/dataset/) annotations are CC BY 4.0, attributed to the TextOCR authors, Singh et al., CVPR 2021. The derivative's resize, blur and compression are explicitly recorded changes.

This is a new full-scene A0 task, **not a pristine independent OCR holdout**: the source previously contributed five word crops to reader diagnostics, including `SKI`. Prior scores and raw reader outputs were not consulted for selection. Pretraining overlap and scene independence remain unknown. One bus photograph and its degraded derivative establish no warehouse or production accuracy. A successful static crop remains a draft for this fixed composition; it is not evidence of detector-driven localization or generalization.
