# Function-transport run: useful adaptation, incorrect final draft

**The selected app fails the objective despite its `draft_ready` state.** On this generated fixture, expected output is only `QZ-4817`. The actual preview outputs `ITEM CODE`, `QZ-4817`, `SHIP TO`, and `IGNORE-552`; the retained report correctly records `exact: false`. Runtime preview success establishes execution, not satisfaction of the user's exclusion.

The run completed in 250.57 seconds with 10 model calls/actions, 5 actual Apple Vision probes, and 1 constructed/previewed workflow. Source identity remained `70bca8f6dec09eb3496f50c168550ac03ecf643efc550176e68def71c52d6d51`.

| Evidence point | Actual result and implication |
| --- | --- |
| Barcode probe `5069dece452f4f6e9dd1ef4a8f7f5e30` | No readings. Next decision explicitly cites this result and changes to OCR. |
| Full-image OCR `3f903a07f622461ca4282bd7931babac` | Four readings with source boxes, including the item code and shipping label. |
| Constructed preview `9d4a1bad1b93465fb3b4b10eea6000f2` | `frame_sample -> OCR -> match("ITEM CODE", contains, emit=all)`. All four texts remain. |
| Cropped OCR `95f184b22cf94d26a92e0eae0ac19338` | Bounds exactly match the item-code box exposed in the actual OCR observation, rounded to six decimals. Returns only `QZ-4817`. |
| Repeated full-image and crop probes | Full image again returns all four strings; identical crop again returns only the code. These repeat already-known experiments. |
| Finish | Selects the original full-image workflow revision `548eddbbbcb94de59e3bc0bcff962a20`; no revised workflow incorporates the successful crop. |

This is real evidence-driven experimentation: the barcode failure drives an OCR experiment, and observed geometry drives a working crop. It is not successful describe-to-built-app behavior, because the effective experiment never becomes the selected executable graph.

The construction summary claimed matching the label would isolate following text. The model-visible node contract explicitly said `match` produces comparison events and does not filter or replace original readings. The final claim that extraction is confirmed for the ready workflow then transfers success from a provisional crop probe to a different full-image graph. Both claims lack support from the actual selected preview.

All action citations belong to their captured citable sets; state revisions and action/observation links match. The final revision and preview evidence ID are authentic and consistent. This is a semantic evidence mismatch, not an invented-ID failure. Content-addressed artifacts were rehashed successfully; the fixture source hash matches every actual probe.

A concrete context limitation contributes: the final independent decision RPC sees the last three probe observations, but the selected preview is only an earlier-observation header. The recent construction entry omits its graph and keeps a hash. Selected revision/preview IDs remain in state and historically citable. A small general improvement is to retain a bounded selected-graph/actual-preview summary in every subsequent context, explicitly separate from provisional probe results. That supplies the missing artifact contents without choosing the agent's strategy or inventing an acceptance rule. The model already saw the full preview in an earlier call and could retrieve it; the limitation does not excuse its final claim.

No inference, backend edit or source mutation was performed by this review. `verdict.json` records exact evidence IDs, the selected graph, integrity checks, source paths and hashes. This is one generated fixture, not representative quality or A0 acceptance.
