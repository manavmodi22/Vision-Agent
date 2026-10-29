# Proposed OCR evaluation — not executed

Use the current Apple Vision bridge as baseline, PP-OCRv5 mobile CPU as first challenger, and Tesseract English fast as a lightweight comparator. Add VL-MLX only after those CPU tests and when the parent grants an inference slot. No candidate may pass merely because it returns plausible text.

## Public data and scope

Start from **TextOCR v0.1**. Its [official dataset page](https://textvqa.org/textocr/dataset/) declares CC-BY-4.0, provides case-sensitive word transcripts/polygons and official image-level train/validation/test partitions. Training has 21,778 images and validation 3,124; test transcript ground truth is not publicly provided by that page. Use public validation labels as our locked diagnostic holdout, and label results accordingly—not an official test-set leaderboard score. `.` indicates illegible/non-English text; exclude those from transcript accuracy, retain counts and do not reinterpret them as empty ground truth.

Images originate in Open Images. [Open Images](https://storage.googleapis.com/openimages/web/factsfigures.html#licenses) lists images under CC-BY-2.0 but asks consumers to verify individual licenses. Preserve each image's author, source/landing URL, license URL and rotation metadata from the [official image manifest](https://storage.googleapis.com/openimages/web/download_v7.html#image-level-annotations). Exclude unresolved/restricted assets from redistributed samples. Keep TextOCR attribution for annotations and original-author attribution for images. Use the official image bytes/geometry and hashes; volatile thumbnails can have different dimensions and must not silently replace benchmark images.

This is a useful public scene-text test, not a warehouse-SKU validation set. Code-like alphanumeric strings, numeric strings, punctuation, small text and perspective form useful strata. Published text annotations are **external ground truth**, not this user's human review. Record `reviewed=false`, source annotation IDs and annotation-file hash. Do not use these imported flags to bypass the application's review/deployment gates.

## Bounded sampling and scene isolation

Proposed first stage: 20 source images for integration smoke only; then 40 development images from official train and 120 holdout images from official validation, with at most 5 eligible crops per image. Keep a full-image output track separate from a ground-truth-crop recognition track. The latter tests recognition given a correct crop and cannot establish detection quality. Record actual counts; do not fill a missing stratum with synthetic examples and call it public data.

The official partitions separate image IDs, but do not by themselves prove scene separation. Before inference, group exact duplicates, near duplicates and visibly repeated scenes/capture bursts; place all crops, transforms and neighboring photographs from a group in one partition. Use SHA256 and image-similarity clustering for candidates, followed by a real human scene-group audit. That audit is **pending**, not completed. If no human audit is available, publish the result as image-disjoint only and explicitly retain the scene-leakage limitation. Exclude overlap groups from the holdout; record every exclusion before looking at predictions. Never resplit after observing failures.

Create a frozen manifest with source image/annotation IDs, byte hashes, original split, scene-group ID and evidence, crop polygon/transform, transcript, license/attribution, and `reviewed_by/at=null`. Seed deterministic selection; separate code-like strings from normal words and report each. Model pretraining overlap with TextOCR is unknown, so this remains a public diagnostic and must later be complemented by unseen, representative warehouse captures with actual human labels.

## Measurements and acceptance

1. Preserve exact output and error text. On crops, score case-sensitive exact transcript accuracy, CER and WER; retain leading zeros and punctuation. Log normalization explicitly and keep a strict raw-string view alongside the app's outer-whitespace normalization. No OCR engine receives the expected answer, a target lexicon, or an answer-dependent whitelist. A fixed code-character whitelist, if later requested, is a separate candidate with its own hash.
2. On whole frames, record detection coverage and text segmentation differences. Do not compare a word list with a line list as though they were identical annotations. Use the same frozen crop/region mapping or score region spotting separately. If an adapter cannot provide regions, show that limitation and keep it out of polygon-IoU comparisons.
3. Test one matching and one nonmatching observed string through exact/contains and matched/mismatched event rules; include leading-zero, hyphen, case and extra-character errors. Use known synthetic strings for these regression checks and label them synthetic, outside public accuracy metrics. Text-free/illegible negatives need explicit evidence of their label status; an unannotated region is not automatically a verified blank.
4. Record model and tokenizer/dictionary hashes, executable/runtime version, CPU/GPU provider, preprocessing, recognition settings and fixed decode limits. Time cold initialization separately from warm p50/p95 latency; record RSS/unified-memory pressure and cancellation/timeout behavior. Run one adapter at a time. Treat a truncated VL response as failure, not partial success.
5. Report per-scene/stratum results, worst exact-text errors, confidence coverage, and paired scene-group bootstrap intervals. Selection target and latency budget must be chosen on development data before opening the holdout; no post-hoc target relaxation. No ranking or promotion until actual observations exist. A small public diagnostic cannot prove deployment readiness.

## Execution boundaries for a later approved probe

- First resolve dependencies into a new isolated environment and save a lock; no production lock edits. Verify package arm64 support and expected hashes before import.
- Download only pinned model files/configuration after a separate work step is authorized. Verify payload SHA256s against `pins.json`; retain licenses/notices. For Tesseract, verify Git blob identity then compute a local SHA256 because the publisher metadata currently exposes a blob SHA1.
- Use local files only; block network during inference and test missing-model failure. No model auto-download, remote inference, silent fallback or broad GPU co-residency.
- Keep outputs under `artifacts/adapter-probes/ocr`; do not modify user projects, annotations or approvals. The catalog remains unsupported until an adapter is actually implemented and validated.
