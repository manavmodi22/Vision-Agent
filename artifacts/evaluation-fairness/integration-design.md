# Evaluation protocol integration

This change separates a numeric metric result from evidence eligible for a declared acceptance decision. Existing labels, review flags and saved reports remain readable.

The service freezes one protocol before a comparison, binding candidate task/scope, all candidate fingerprints, selected reviewed dataset, source/group/split assignments, acceptance policy and evaluator recipe. Every score in a comparison references that exact protocol. The executor checks the snapshot before and after scoring; changed candidate, pixels, annotations, grouping, policy or recipe requires a new comparison. OCR and barcode cannot share an objective merely because both produce text.

Human configuration is exposed through typed, optimistic-concurrency API routes. Group labels represent declared provenance; the API must not infer independent scenes from file names. Iterative validation and acceptance are separate roles. Acceptance eligibility is restricted by explicit coverage policy, source independence and prior exposure; setting a policy does not manufacture untouched evidence.

Approval uses an explicit `approval_scope` (`promotion` or `local_trial`) and the existing `override_reason`. Promotion requires current protocol evidence and numeric success. A local trial requires current evaluated evidence plus a reason even when the numeric target passes; unknown, correlated or fixture data can support this bounded scope. The existing recording caps remain 500 frames per uploaded-media run and 3,600 seconds per live session. Neither scope validates temporal event behavior, which the frame-based evaluator does not measure. No agent tool can grant either approval.

The service, native API, build coordinator and MCP comparison path use the same protocol checks. Approval stores the protocol identity. Recorded and live execution revalidate it before committing evidence; legacy approvals are readable but cannot authorize new recordings. Agent summaries name the evidence limitations and offer configuration or a deliberate trial, not automatic promotion.

Focused acceptance checks: same-protocol comparison, distinct OCR/barcode rejection, changed source/group/split/policy/recipe invalidation, legacy rejection, explicit trial despite numeric success, independent declared acceptance path, unchanged boxes/review flags, no effects before human approval, and no temporal alert-quality claims.

“Untouched acceptance” here means not previously used for this project's model inference, selection or training. It does not mean unseen by a human labeler, and does not establish separation from unknown upstream pretraining data. Users may import fresh sources, reserve their groups, and manually review ground truth before the selected candidate's one acceptance run. Normal model previews and suggestions must skip reserved acceptance; a shared exposure record prevents previously used groups or renamed copies from becoming fresh by editing their assignment.

Local trials keep output local. Configured external delivery is suppressed and explicitly identified as disabled in returned evidence warnings; destination settings are preserved for separately eligible promotion. This change grants no outgoing notification authority.

Live inference records only the normalized pixel exposure token before executing an in-memory frame, including preview-only sessions. It does not retain a preview frame or event. A later identical-pixel import therefore retains its model-use history. Imported sources from before exposure tracking are conservatively unknown, and prior saved model proposals/previews/evaluations cannot become untouched merely by updating the application.

Software verification includes an explicitly mocked detector for the positive independent-acceptance route, with separate development and reserved imported groups. Its passing metric values exercise API/state behavior only and are not model-quality evidence. The real geometric fixture tests remain identified as synthetic and require explicit local-only trial consent.

Current limit: workflows containing rule/match/event-sink behavior do not qualify for promotion through this image-only acceptance recipe. They can be explicitly approved for local trials, whose external delivery stays disabled. Therefore this integration does not authorize automatic external event delivery through the new quality gate. Existing explicit destination tests remain separate human actions. A measured event/temporal protocol and any additional delivery consent are outside this slice.
