# Public cropped-word reader diagnostic

Both readers executed the same frozen 100 word crops from 20 TextOCR validation
images. Expected transcripts were available only to the separate scorer after raw
inference outputs had been saved. No execution failures or byte-exact duplicate
inputs occurred. Public labels remain unreviewed by the app; no project quality
gate, model promotion or deployment was created.

| Endpoint on the original-size crops | Exact crops | Character error rate | Word error rate | No text returned |
| --- | ---: | ---: | ---: | ---: |
| Apple Vision, English, correction disabled | 33/100 | 54.25% | 75% | 45/100 |
| Isolated PP-OCRv5 mobile detector + English recognizer | 16/100 | 75.38% | 88% | 67/100 |

These measure **complete reader endpoints applied to ground-truth word crops**.
Paddle still performs detection before recognition; this is not a recognizer-only
benchmark or a full-scene text-spotting score. Both receive the original-size crop
with the same fixed border and no transcript hint. There is no case folding,
Unicode replacement, dictionary repair or best-output selection. The engine's
normalization strips outer region whitespace, sorts regions case-sensitively and
joins them with newlines. Failed calls would remain in the denominator.

The sample includes 48 crops below 32 pixels high, 33 from 32–63 pixels and 19 at least
64 pixels. Exact matches in those groups are Apple 12/11/10 and Paddle 3/4/9. This
suggests input size and the repeated detection stage deserve a controlled
preprocessing experiment; it does not establish causation or justify silently
resizing, replacing outputs, changing a model or promoting a new default.

Apple's median 227 ms / p95 276 ms includes launching its bridge per image, PNG
transport and framework work. Paddle's median 5 ms / p95 94 ms excludes its one-time
1.354 s import/initialization and often reflects a no-detection result. These are
different process lifecycles, so they are not an end-to-end app speed ranking.
Paddle ran in a serial isolated process with actual OS network denial; the Apple
run used the native system framework without an added process sandbox.

Apple used debug binary SHA256
`cbb096c96cbecddae97689e063d89491fe764a43d9e0ccec00f0356fc48488f3`.
Later native changes only restore mixed-workflow output visibility; this report
continues to identify the exact binary actually benchmarked. Paddle's raw probe
retains source, package, model and loaded-library identities and its build report
records the image-only OpenCV wheel. Its production adapter is not registered.

Evidence: `textocr-manifest.json`, `textocr-selection-audit.json`,
`apple-textocr-raw.json`, `paddle-textocr-probe-raw.json`, the scoring projection
`paddle-textocr-raw.json`, and both `*-scores.json` files. The source is
[TextOCR](https://textvqa.org/textocr/dataset/), with image provenance and attribution
in the manifest. These 20 public scenes do not establish warehouse label accuracy;
scene grouping and upstream model pretraining overlap are unknown. Geometry was
not scored. Representative independent acceptance data remains required.
