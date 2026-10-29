# Native workflow authoring

Owner: native_app. Workflow is a structured block editor with a parameter
inspector and a preview. Local-agent generation is a collapsed secondary panel.
Users can create a workflow from the dataset's class ontology, then add/remove or
reorder registered blocks, change labels/models/thresholds/rules, choose compatible
upstream output ports, and set the evaluation metric and target.

`GET /blocks` supplies typed port definitions and parameter JSON Schema. New block
IDs are unique. New input connections select a matching existing upstream port
when available; unresolved inputs remain visible and must be repaired. Deleting a
block does not silently redirect its dependents. Parameters support strings,
numbers, booleans and text lists, with a validated JSON object editor for nested
values such as crop geometry. The engine remains authoritative for schema,
license, model, connection, cycle and evaluation constraints.

`PUT /projects/{id}/candidates/{index}` validates and persists the explicit Save
request together with the originally loaded `base_spec`. A stale baseline returns
409; the draft remains on screen, and Revert explicitly loads the latest saved
workflow. The baseline advances only after a successful save. Edits typed while a
save is in flight remain as a new unsaved draft. Compiler errors also leave the
draft on screen. Accepted changes invalidate
previous evaluation and deployment evidence. The Run screen can execute approved
workflows on separately chosen new media without changing the dataset or holdout.

Native checks verify that image inputs cannot choose detection outputs, detection
inputs exclude image outputs, source frames have the correct port type, and added
nodes receive unique IDs. The packaged application passes 33 native self-tests.
