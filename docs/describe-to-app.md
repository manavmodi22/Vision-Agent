# Describe-to-app orchestration

The primary action is a natural-language goal. It starts a durable background
build that calls the existing local planner and MCP compiler/inference tools,
surfaces the actual preview, and prepares label proposals automatically. Workflow
editing and annotation are contextual corrections rather than required setup.
Follow-up goals include the existing brief, conversation and candidate graph.
Technical defaults come from the planner; only unresolved business meaning
consumes the project's existing three-question clarification budget.

The neutral public DTO is `spec/build.py`. POST `/projects/{id}/build` with
`{prompt}` starts work; GET the same path returns the latest flat `BuildStatus`.
POST `/projects/{id}/build/continue` takes `action: continue|improve`, an optional
clarification `prompt`, and `training_approved` (default false). Native polls while
running and displays the returned preview and actual work log without another
preview click. `project` always reflects the current saved project. Missing media
becomes an attach-media checkpoint without consuming model clarification budget.

The engine control plane commits the exact planner operation token and persists
progress. Agent vision actions cross MCP: label proposal, context reading,
evaluation of every candidate, training, preview and approved operation. Only
the human-facing continue endpoint can authorize training. Approval is recorded
against the current candidate and annotation hashes and consumed once. The
agent cannot create deployment approval. Existing `/deploy` remains the human
gate; continue then runs only the currently approved selected candidate.

Human checkpoints are clarification, marking missing spatial regions, review of proposed labels, explicit bounded
training approval after a missed target, and deployment approval. Proposed labels
stay unreviewed and preserve manual boxes and reviewed rows. Evaluation requires
the engine's reviewed-image and held-out-set conditions. Candidate selection
prefers passing candidates and respects lower-is-better count MAE versus
higher-is-better precision, recall and text accuracy. Comparison requires the
same metric, target, reviewed evaluation dataset, and detection scope. Scope
includes the selected classes and the actual final-branch zone polygons.
Incomparable scopes pause for clarification rather than selecting an older,
narrower goal as the winner.

Each active segment has a wall-clock and tool budget; training is limited to two
two-minute attempts per build and never starts without the human action. Durable
records and tool traces survive app restart. A dead worker becomes interrupted;
reversible stages can resume. Source/pipeline changes invalidate stale work.
Annotation changes are expected only at review checkpoints. A crash during an
event-recording run has an uncertain outcome and is never automatically rerun.
No successful evaluation, human review, training result, or deployment approval
is inferred from model text.

## Implemented refinements and sample policy

Natural-language changes use the configured local model to produce a typed batch
against the actual graph. Exact confidence and additive-class commands also have
a bounded deterministic path. Patches cover confidence, added/removed/replaced
classes, count thresholds and hold durations, reading comparison values/modes,
sample rate and evaluation targets. The batch is compiled and previewed over MCP,
then committed against unchanged source, model, annotations, ontology, and
holdout evidence. Confidence changes preserve manual transforms, zones, rules,
evaluation targets and existing annotation review state. Adding a detector class
preserves boxes and provenance but resets review flags, because old reviews did
not establish ground truth for the expanded class set. Unsupported or ambiguous edits are explicit
clarification checkpoints; they never silently replace a user's graph with a
template. The default detector policy uses OWLv2 for arbitrary object classes;
this is an authored policy, not a claimed language-model model-selection result.

Datasets larger than 50 images receive a first-ten-image evaluation subset if no
holdout already exists. Selection never marks labels reviewed and does not
establish scene independence. Existing holdouts are preserved. Suggestions retain
prior proposals and manual labels; work-log wording reports their observed state
without claiming fresh inference for skipped images. Current training requires
20 reviewed images and an available slot within the three-candidate limit.

## Observed native acceptance

`artifacts/agent-experience/acceptance.json` records the native goal-to-app flow on
the downloaded NVIDIA warehouse samples: the user described counting people,
received an actual five-frame preview, and reached a review checkpoint with
20 unverified proposal images. A confidence follow-up changed exactly the
detector's threshold from 0.4 to 0.15 while preserving the graph, increasing
preview detections from two to seven. Continuing without reviewing labels stayed
at the review checkpoint, with no evaluation or deployment. These are observed
predictions and workflow checks, not an accuracy claim.
