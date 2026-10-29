# Visible graph syntax and decoder ordering

The root agent identified the primary discriminator-order defect and applied the `Node.type`-first fix. Local schema inspection before that fix confirmed OCR/barcode fields were ordered `id,image,model_capability_id,model_reason,type`, while most other variants were `id,type,...`. Once generation chose `id,type`, inference variants were excluded by the ordered grammar. The crop receipt `34cb2c43bd1d47bba3d22836ad095cf7` repeated that failure three times.

The pinned `b11963` source confirms the mechanism: [JSON object insertion order](https://github.com/ggml-org/llama.cpp/blob/b11963/common/json.h#L20-L22), [ordered property collection](https://github.com/ggml-org/llama.cpp/blob/b11963/common/json-schema.cpp#L134-L153), and [required-property grammar concatenation](https://github.com/ggml-org/llama.cpp/blob/b11963/common/json-schema-to-grammar.cpp#L683-L730). The installed local release contains binaries, so the exact upstream tag was inspected after checking the installed symbol and server version. This establishes the grammar mechanism; actual generation success still requires another live run.

After the root authorized production edits, the minimal prompt complement was implemented in `agent/planner.py` and `agent/prompts/graph.py`:

- `context.node_fields` derives flat required fields from the actual graph schema. Its compact JSON occupies 478 characters, excluding the context key. No manually maintained field table is introduced.
- Explicit `$ACTUAL_ID.PORT` guidance distinguishes recognition from comparison and explains why a match cannot consume an image.
- A small, valid source → OCR → exact-match example selects an OCR capability from captured eligible options. No eligible reader means no example. Its literal is `EXAMPLE-123`, and it omits crop/resize so the planner still must author the user's transformations.
- Full playbook bodies and identities, model options/evidence/classes, actual catalog ports and the 24,000-character guard remain. Repeated prose was shortened; the default `fps 2` remains explicit.

Focused tests check schema-derived fields, example validity/reference resolution/model binding, unavailable-reader behavior, all three captured context sizes, and preservation of model evidence, class vocabulary, ports and playbooks. No language-model request was issued by this child. There is no fallback, generated-plan repair, retry-budget increase, evaluation or approval change.
