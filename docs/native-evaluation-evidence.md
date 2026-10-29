# Native evaluation evidence

The Agent conversation keeps the numeric result on the reviewed images separate
from whether those images support quality promotion. A target passing is not a
promotion verdict. Historical results remain readable; absent protocol evidence
is unknown and requires a fresh evaluation before a new approval.

The existing candidate comparison presents measured value, target and image count.
An adjacent evidence section presents only the server's eligibility verdict,
grouping facts and reasons. Unknown source groups, correlated scenes, validation
reuse and acceptance contamination have concrete correction actions rather than
being hidden behind a passing score.

“Edit evaluation evidence” opens a contextual sheet from the Agent conversation.
It loads the current images and saved protocol. Source and scene grouping,
evaluation policy and acceptance selections are edited there with revision checks;
opening or saving this sheet never marks annotations reviewed. A conflict preserves
the draft and asks for an explicit reload. Closing returns to the same conversation.
Saving changed evidence requires re-evaluation and does not itself establish an
untouched acceptance set. The engine owns usage history and eligibility.

Deployment approval explicitly distinguishes quality promotion from a bounded
local trial. A trial always needs a reason, even when the numeric target passes.
Its server-returned recording limits and limited evidence status remain visible
after approval. A local trial disables external alert delivery and does not
establish temporal event accuracy. The UI never converts a target miss or unknown evidence into a
trial implicitly, and never grants a local trial a validated-quality label.

No new setup dashboard is required to describe a goal, attach examples or preview
an application. The editor appears contextually when evidence needs correction.

## Wire contract and behavior

- `GET/PUT /projects/{id}/evaluation/config` exchanges the configuration revision,
  images and policy. PUT sends `expected_revision` plus only editable assignments
  and policy. Source identity, hashes, frame coordinates, group provenance and
  exposure reasons never appear in the mutation payload.
- Policy declares intended use, the basis for independent groups, required
  acceptance group names and the scope/limits of coverage. Group count is not a
  representativeness score. Known synthetic origin is immutable.
- `GET /evaluation/readiness?candidate_index=N` provides the actual acceptance
  blockers and availability. The native action remains disabled until the server
  says that candidate is ready. This read does not consume reserved data.
- `POST /evaluation/acceptance` evaluates the selected candidate. The separate
  `BuildStatus.acceptance_evaluation` card never overwrites candidate-ordered
  validation comparisons. Existing model failures and correction actions remain
  visible, with acceptance failures identified separately.
- Approval sends explicit `approval_scope=promotion|local_trial`; a trial needs
  `override_reason` even when the numeric target passed. Missing legacy evidence
  is never upgraded by default decoding. Server freshness checks remain final.

Native checks cover historical decoding, target/eligibility independence, the
acceptance scope requirement, explicit trial reasons, read-only provenance,
synthetic origin protection, CAS revision payloads, group clearing, conflict draft
preservation and actual readiness blocker decoding. No model inference is needed
for those contracts; native UI acceptance remains a separate verification.

The contextual importer calls the existing pure media ingestion route, then
reserves only newly returned image rows as acceptance before any model action.
If ingestion succeeds but reservation fails, current configuration is reloaded
and the new image IDs remain selected in an unsaved reservation draft. The UI
explicitly reports the partial result and does not repeat ingestion. Normal
preview and proposal endpoints exclude reserved acceptance data; annotation
review remains a human operation.

Native validation is recorded in
`artifacts/native-evaluation-validation.json`: Debug and Release each passed
159 deterministic checks, ten historical backend payload decodes and four current
API fixture checks. API fixture inference is explicitly mocked.

The final packaged walkthrough is separate in
`artifacts/evaluation-fairness/native-ui-qa-7f62.json`. It used a temporary generated
fixture project to inspect evidence, save 16 validation assignments, re-evaluate
through the conversation, and check the trial reason controls. Annotation bytes
were unchanged; the trial dialog was cancelled, with no approval or recorded
events. The owned QA project was archived outside the app's project list. This
verifies UI/software behavior and does not measure real-world detector accuracy.
