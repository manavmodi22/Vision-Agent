# Public OCR diagnostic sample

`textocr-manifest.json` freezes 20 images and 100 word crops from the public
TextOCR v0.1 validation split, before either reader is evaluated. Selection uses
SHA256 of a fixed seed plus source IDs. Each image contributes at most five
published, legible, ASCII transcripts. ASCII eligibility does not imply English.

Run `scripts/prepare_textocr.py --root .visionapp/datasets/textocr-v0.1 --count 20
--output artifacts/reader-evaluation/textocr-manifest.json` to reconstruct the
local images and crops. The annotation JSON is pinned by SHA256. Crop inputs and
original images remain ignored local data; this repository contains provenance
and published transcript/geometry records, not redistributed source images.

Sources: [TextOCR](https://textvqa.org/textocr/dataset/) (annotations CC-BY-4.0;
Singh et al., CVPR 2021) and the
[Open Images source manifest](https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv).
Every selected image has an official CC-BY-2.0 declaration, author, original URL
and landing page in the manifest. Individual Flickr license pages have not been
reverified; do not redistribute those images from this repository.

Crops use the bounding rectangle plus a fixed 5%/minimum-two-pixel border. The
original downloaded image dimensions must exactly match TextOCR's annotation
space. Source rotation metadata is retained but not applied: the published
coordinates include sideways text. A contact sheet was visually inspected for
crop alignment, including the nonzero source-rotation case. That inspection is
not transcript review, scene-group review or an accuracy result.

These are word-crop recognition diagnostics, not full-image text spotting,
warehouse-SKU acceptance or production quality. Published labels remain external
ground truth with `reviewed=false`; no app project or approval is created. Scene
grouping/near-duplicate audit and upstream pretraining overlap remain unresolved.
Small, rotated, partial and difficult crops are retained, and all inference
failures must stay in the denominator. No expected transcript is provided to a
reader at inference time. Raw strings are scored case-sensitively, without Unicode
substitution, dictionary repair or LLM correction.

## Runtime audit boundary

`current-opencv-runtime-audit.json` records a live inspection of the existing app
Python environment. Its installed `opencv-python-headless` 4.14.0.94 native
`libavcodec` reports GPLv3-or-later with GPL codec build options. Consequently the
whole packaged dependency stack must not be described as uniformly permissive
based on OpenCV's top-level license. The separate reduced Paddle experiment is
being audited independently. This observation does not change installed packages
or establish release redistribution compliance; packaging remediation and notices
remain required before a release claim.
