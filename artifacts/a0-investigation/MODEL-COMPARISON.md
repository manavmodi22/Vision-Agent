# Frozen generated-fixture comparison

29 October 2026. Both models failed to produce an application draft. The 9B
candidate reached actual vision experiments but then asked the user for crop
coordinates already present in an earlier observation. Neither result passes A0.

| Model | Outcome | Calls / actions | Executed vision probes | Elapsed |
| --- | --- | --- | --- | --- |
| Qwen3-14B Q4_K_M | Asked the user to choose a model after repeated detection searches | 11 / 11 | 0; one attempted probe was rejected | 626.47 s |
| Qwen3.5-9B Q6_K | Asked the user for an item-code bounding box or label format | 10 / 10 | Apple OCR: four readings; barcode: zero readings | 560.96 s |

The objective, generated pixels, executable tools, task limits and 16K context
were held constant. Each run used its own project/task/media identifiers. Engine
source before and after both runs was
`503a046821a66aa02d6010394b346415b3a7670010cba7cfd5df06d64a1fc3e4`.
Both used the actual local planner, manager, MCP and adapter paths. Expected
output `QZ-4817` was held outside the planner context. No selected preview existed,
so neither run has a successful reference comparison.

Full evidence:

- [14B report](qwen14-16k-baseline/report.json), [model/action ledger](qwen14-16k-baseline/task.json).
- [9B report](qwen35-9b-16k-candidate/report.json), [model/action ledger](qwen35-9b-16k-candidate/task.json).
- [Server setup](model-comparison-setup.json), [9B artifact provenance](qwen35-9b-qualification.json).

The 9B selected OCR using the returned capability descriptions, recovered from
inspecting an ineligible graph block by inspecting the actual adapter, and ran
OCR. It received `ITEM CODE`, `QZ-4817`, `SHIP TO`, and `IGNORE-552`, each with
source geometry. It repeated the adapter inspection three times, then chose a
barcode experiment citing the OCR observation. That experiment returned nothing.
Its final question was unnecessary: earlier OCR had already supplied the
requested coordinates. This is a recorded evidence-dependent experiment change,
but it did not solve the task or produce a compiled preview.

The context reconstruction explains a contributing defect, not all model errors:
repeated metadata displaced the OCR observation before calls 9 and 10. The model
had also ignored its geometry while it was initially visible. The subsequent
[context fix replay](context-retention-replay.json) restores those values within
the token budget; a fresh model run remains necessary to measure improvement.

## Resource and interpretation limits

Both planner servers and the existing Cosmos server were initially resident;
planner inference ran sequentially. Swap grew and kernel pressure was observed
at warning level during the candidate run. After the baseline completed, its
idle server was [gracefully unloaded](baseline-resource-unload.json) during the
candidate run. Pressure was normal at that exact unload sample. Consequently,
the elapsed times are observations under different residency conditions, **not
a controlled speed ranking**. The configured default model was not changed;
its server must be restored after the isolated candidate tests finish.

The 9B artifact is a pinned third-party Unsloth conversion with verified bytes;
its exact conversion-source commit is not established. These are two exploratory
runs on a generated software fixture, not independent vision-quality or model
generalization measurements. The [public original scene](bus-original-frozen/README.md)
ran separately from a sealed snapshot of this same engine revision and also
failed to produce a draft. Its degraded counterpart is postponed; no paired
acceptance result is claimed. Subsequent context diagnostics and fixes are
recorded in the [evidence index](README.md).
