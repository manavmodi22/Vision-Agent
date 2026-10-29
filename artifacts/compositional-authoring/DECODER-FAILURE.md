# Retained local-planner failures

The first run stopped before generation because the prompt plus declared output
schema exceeded the 24,000-character budget. The compact prompt retains selected
playbook bodies/identities, actual catalog ports, model evidence and class vocabularies.
The limit was not raised. See `live-context-budget-failure.json`.

The next run on source `dd1320a640430c8408558d60dcdc65c80c13553d9becb73b2a3b868a0ab5b9e9`
failed both required cases after three model responses each. The crop proposal
omitted OCR and referenced a nonexistent sample ID. Parallel-reader proposals
used `frame_sample` nodes named as readers. Validation prevented preview execution.
The full responses remain in the operation paths in `live-invalid-graphs-failure.json`.

The schema declared OCR/barcode fields in `id,image,model_capability_id,model_reason,type`
order, unlike other nodes' `id,type,...` order. The installed llama.cpp b11963
[converter emits required object properties in sequence](https://github.com/ggml-org/llama.cpp/blob/b11963/common/json-schema-to-grammar.cpp#L683-L730).
After an `id,type` prefix, the grammar therefore excludes the reader alternatives.
All node schemas now put the type discriminator first; a regression checks every variant.

The [same version's grammar documentation](https://github.com/ggml-org/llama.cpp/blob/b11963/grammars/README.md#L120-L128)
also explains that response-format schemas constrain decoding without becoming
model-visible instructions. The prompt consequently needs an explicit field guide.
These diagnoses and software checks do not establish a successful rerun; later
acceptance receipts must record that outcome separately.

The full suite on this failed source was interrupted to make the schema correction.
Its partial log is retained and is not an overall test pass. The candidate package
was built but was not installed over the previously verified native app.
