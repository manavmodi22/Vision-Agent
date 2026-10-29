# Workflow-visibility live run: correct fixture output, rejected finalization

**The saved graph works on the supplied fixture; the autonomous task still ended inconclusive.** Actual preview of selected revision `532c161858cb465ebe3c87b6dee75fad` returns only `QZ-4817`, excluding `ITEM CODE`, `SHIP TO`, and `IGNORE-552`. The report's independent exact-reference check is true. This is stronger than the earlier successful probe: the effective crop is now in the saved executable graph.

The run used 13 model calls, 12 completed actions, 5 real Apple Vision probes and 1 actual workflow preview in 540.63 seconds. Source remained `eccdf45df253baccdd3bc3a73f56b1746865b5f95823629664cd3cf5b5c49801`. The model first explored detector metadata, then changed to code reading. Empty barcode output drove OCR; full-image OCR exposed the code's box; a crop matching that observed box returned only the code. The model authored `frame_sample -> crop -> OCR` with the same box and Apple Vision binding. Source-image and artifact hashes match the saved evidence.

The final decision named the correct selected revision, but `evidence_ids` contained the latest full-image probe `822cfccba67743e6ac7b19c0fbab9cc7`, not the selected workflow preview `2a0fb1139b6743639c7cb0044ae3ec30`. The host correctly rejected draft_ready before reservation/dispatch and persisted an inconclusive stop. The model-call receipt itself is completed with error=null; the downstream host action validation supplied the terminal stop reason. This was a relational evidence error, not an invented ID. The final call had the selected graph, exact preview values and preview ID visibly available; missing context does not explain this failure.

The saved output supports the narrow claim that the fixture's item code is isolated. It does not establish layout-independent extraction. Crop bounds `[0.050781, 0.383333, 0.21875, 0.491667]` are fixed at construction, not dynamically detected on each future frame. No shifted layout, other item code, scale/rotation variation or independent image was evaluated. The final summary limited its success claim to the available image, but the draft still needs an explicit static-layout limitation when presented to a user.

Other qualifications:

- The graph proposes `text_accuracy` target 0.0. This is not an approved or meaningful acceptance threshold; the true fixture result comes from the independent reference comparison, not that target.
- Preparation and construction leave `based_on_observation_ids` empty despite observation-derived choices. Their separate `evidence_ids` do identify real crop/full-image/metadata observations, so this is incomplete provenance expression rather than absent evidence.
- After a correct preview, the agent probed the label region (returning only `ITEM CODE`) and repeated full-image OCR (all four readings). These experiments did not alter the selected graph.
- The report correctly calls the media a generated software fixture, but project.json says synthetic=false and data_origin='User imported media'. Preserve this historical discrepancy; future harnesses should label generated media accurately without granting fixture-only model access.

All referenced content-addressed artifacts were rehashed successfully. Completed action state revisions/citations/receipt links are valid. Project candidates/evaluations remain empty, annotations unreviewed, and approval/deployment absent. The preview emitted no events.

The next narrow reliability issue is finalization feedback: expose the selected-preview membership rule in pre-dispatch grounding or return its validation failure as bounded corrective feedback, retaining the host check and rejected attempt. Do not silently replace the model's evidence ID. Then require a genuine completed trace and a separate layout-variation test before broader qualification.

`audit.json` contains every final finish argument, model-call status/error, visible evidence IDs, exact graph/checks and original-file hashes. The preserved report/task under `gpt-oss-qualification/workflow-visibility-live/` were independently confirmed byte-identical to those originals. No inference, answer injection, production source edit or task mutation was performed by this audit. This is fixture-level output success with incomplete agent completion, not A0 acceptance or model promotion.
