# Fixed second-scene detector comparison

Thirty frames from NVIDIA PhysicalAI-SmartSpaces 2025 Warehouse_016 / Camera_01, pinned revision `2cbe9563cbe9f47f846e5c871ee994572bbbc60e`. CC-BY-4.0; attribution: NVIDIA Physical AI Smart Spaces, Wang et al. (2026). The frames and confidence/IoU thresholds were frozen before inference. This scene was not used by the prior Warehouse_015 experiments.

**None of the models passed the declared 80% recall target.** These are published synthetic labels, not human-reviewed app annotations or real-world acceptance. No model, approval, review flag, or recorded event was changed.

| Model | Device | Precision | Recall | Count MAE / frame | Recall gate |
|---|---|---:|---:|---:|---|
| owlv2-base-patch16 | mps | 50.9% | 72.3% | 1.70 | Failed |
| rtdetr-v2-r18 | mps | 12.4% | 75.9% | 19.03 | Failed |
| yolox-s-onnx-coco | CPUExecutionProvider | 37.8% | 52.7% | 1.73 | Failed |

All models used the same 30 images and 112 published person boxes, confidence 0.15, class-aware greedy one-to-one IoU matching at 0.5. Source non-person classes remain negatives: humanoid robots are not relabeled as people. OWLv2 and RT-DETR used the frozen packaged `d403` engine; YOLOX used its isolated, pinned official CPU probe and is not an app capability.

OWLv2 has the lowest count MAE in this specific comparison. This is not a universal ranking. Precision/recall expose mistakes that count error alone can conceal. Post-run analysis found unmatched predictions overlapping published humanoid-robot boxes; these include duplicate predictions and are not counts of unique robots.

| Model | True positives | False positives | False negatives | FP predictions overlapping a humanoid robot |
|---|---:|---:|---:|---:|
| owlv2-base-patch16 | 81 | 78 | 31 | 71 |
| rtdetr-v2-r18 | 85 | 598 | 27 | 166 |
| yolox-s-onnx-coco | 59 | 97 | 53 | 58 |

## Evidence and limits

- `protocol.json` and `protocol.sha256`: frozen samples, model set, thresholds and attribution.
- `source-ontology-audit.json`: original class inventory; six evenly spaced label composites were visually checked. Full labels remain unreviewed.
- Per-model JSON: every prediction, source/weight identities, input hashes, measured wall time and process RSS.
- `comparison.json`: aggregate metrics and per-frame failures.
- Timings include decoding/postprocessing and initialization; CPU and MPS differ. They are not controlled sustained-throughput or GPU-memory measurements.
- Confidence scores are model-specific and uncalibrated. A common numeric threshold is a reproducible baseline, not each model's best operating point; threshold tuning needs separate validation data.
- Frames remain correlated within one scene/camera. After inspecting these results, this set is validation evidence; do not reuse it as a sealed acceptance test after tuning.
- Pallet, forklift, damage, segmentation, OCR and event correctness are outside this comparison.

[Official dataset](https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces)
