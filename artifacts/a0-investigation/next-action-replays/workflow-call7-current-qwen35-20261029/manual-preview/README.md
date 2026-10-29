# Manual preview of the exact 9B graph

The saved model-generated graph was executed unchanged on a byte-identical copy
of the original generated fixture, using `compose_graph`, current planning options,
`compile_pipeline` and `run_pipeline` with the real local Apple Vision adapter.
This was a manually authorized diagnostic, not an investigation action or an
agent-built app. No InvestigationStore or synthetic model-call authority was
created, and no LLM request was made.

The graph compiled and ran, but the actual text output was:

- ITEM CODE
- QZ-4817
- SHIP TO
- IGNORE-552

The expected fixture output was only `QZ-4817`. The exact reference check is
**false**, and all three excluded readings remain. The proposal's claim that its
full-image OCR ignores the shipping label is therefore contradicted by this
actual preview. Compilation success does not establish the requested behavior.
This is one generated fixture, not a scored evaluation or acceptance result.

`actual-preview/` preserves the untouched proposal, graph, planning options,
model bindings, compiled spec/plan, full RunResult, reference check and receipt.
The result contains actual per-reading boxes, confidence and adapter identity.
`manifest.json` hashes the saved output files. `preview.py` records the exact
one-shot procedure and refuses to overwrite its existing workspace/receipt.

The new isolated workspace recorded normal preview exposure. It had zero saved
candidates, evaluation results, reviews and events before and after; no approval,
deployment or investigation state was created. Project and annotation documents
were unchanged during preview. The original project tree, task, report, proposal,
fixture, native bridge and production source passed immutability checks.

The first preparation attempt lacked `VISION_APP_BINARY` and stopped before
compilation/inference. `preparation-failure.json` preserves this failure. The
successful second preparation used the same existing native bridge configured by
the source run (`dist/VisionApp.app/Contents/MacOS/VisionApp`) only in that process;
no server or application settings were changed. The first workspace was retained.
