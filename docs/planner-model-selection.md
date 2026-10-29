# Per-candidate model selection

The planner receives a compact, typed projection of the actual installed model
catalog through MCP. It names a model capability and a proposed reason for each
candidate. The projection records task compatibility, adapter contract, open or
closed vocabulary, installation prerequisites and synthetic provenance. A model
choice is a hypothesis for a bounded experiment, not an accuracy claim.

The exact options snapshot is captured before the model call and retained with
the operation and immutable BuildPlan. Validation rejects missing, unknown,
unavailable, incompatible and synthetic-on-real-data selections. Closed models
must cover every requested class exactly. The compiler resolves each candidate
from its saved option; the executor consumes that saved choice. No model is
silently substituted or installed. Changed selected capability metadata must be
reconsidered before execution; existing model/data hashes guard later changes.

New LLM outputs must state the capability ID and proposed reason. Legacy saved
decisions keep their old host-selected detector semantics for replay. Explicit
fixture detector settings constrain detection options in synthetic projects;
reading fixtures still use the actual native reading adapter. New real builds
do not force OWLv2. Candidates retain a shared task, metric, target and holdout
before comparison; human label, training, deployment and delivery gates remain.

This change selects among implemented detector/OCR/barcode adapters and bounded
typed workflows. It does not introduce arbitrary graph topologies, code,
segmentation, tracking, downloads or new model adapters. Prerequisite readiness
permits a validation experiment; it does not establish measured quality.

The planner selects compatible candidate models; the surrounding experiment
sequence remains host-authored policy. Plans now describe only the current
authorized phase and the relevant evaluation step. Reading-only plans do not
propose detector training, and no plan invents an external-delivery setup step.
Human checkpoints describe conditional gates rather than claiming they are
mandatory future work or that current labels have already been reviewed.

Validation uses contract cases plus actual stdio MCP compilation and synthetic
fixture previews, including saved-option replay and legacy plan hashes. These
tests do not measure learned detector accuracy. Discovery checks installed prerequisites and runs the catalog's tiny
CPU fixture self-test; it does not load learned models or install dependencies.

## Recorded provenance and default selection

Options version 0.2 separates executable compatibility from default suitability.
Local manifests may declare `use_scope`, its evidence reference, initialization
and training state. Existing manifests remain unchanged and missing fields remain
unknown. The prompt receives compact recorded training/base/sample/step facts,
preserved classes and an explicit `none_attached` evaluation status. An evaluation
dataset hash is never presented as a score; historical result discovery and
current-weight-matched score linking are not implemented by this change.

Models declared `engineering_smoke` or `untrained`, and local models without an
evidenced `user_candidate` registration, are excluded from generic choices with
visible reasons. Unknown suitability does not mean proven bad. A user candidate
remains eligible regardless of filename, architecture or small training count.
Known upstream adapters remain baseline experiment options when compatible and
installed; neither initialization nor eligibility establishes project accuracy.

An exact affirmative request such as `Use local-example for this experiment` or
`Compare local-example and local-other` can include an experimental checkpoint.
The MCP server derives this authorization from the durable operation's originating
brief, not an LLM-supplied flag. The receipt persists the brief hash and exact IDs.
Negation, mention-only questions and quoted label data do not grant eligibility;
human clarification commands are supported. This intentionally conservative
direct-command parser is not a general natural-language permission interpreter.
It never bypasses availability, vocabulary, task, fixture-source or approval gates.

Approved TrainingJobs now declare only their **fresh unique output** as a user
candidate after validating result identity, backend/base lineage, and training/evaluation fingerprints.
The job records a weights/manifest receipt before candidate scoring; score hashes
are computed afterward. Existing model registrations are never rewritten. Direct
low-level trainers retain unknown purpose. The host records `optimization_completed`
after verifying at least one optimizer step; initialization stays unknown unless
already recorded by verified lineage. A completed optimization is not quality
promotion, deployment approval, or evidence of independent scenes.

Historical 0.1 options and plan replay remain readable. New live decisions use the
current policy, and changes to selected provenance invalidate their captured
options. No existing installed model was reclassified in this implementation;
evidence and current weights must be checked before any later migration.

The prompt prioritizes eligible options. Noneligible experimental inventory is
limited to eight capability IDs with purpose/reason, plus explicit total, omitted
and purpose counts; the full captured receipt remains available. Exact requested
experiments move to the eligible set and retain their training facts. Regression
coverage renders the complete saved warehouse goal/context/playbooks/schema,
a 1,318-character goal, and a 100-experiment inventory under the unchanged limit.

At runtime source `d403b8dc578b7be2b33b9b1065bbf90a288d01eb60cdd71dbd06b902b611428b`,
two additional actual Qwen3-14B/MCP checks passed. Exact `ABC-990` reading/matching
used one model call in 46.539 seconds. A request for two installed person-counting
models selected local RT-DETR and SSDLite checkpoints, compiled and previewed both
on the same three public NVIDIA frames, preserved confidence 0.2 and count MAE
target 0.5, and recorded no events. That run took 87.423 seconds with one model
call. The captured reports are
`artifacts/stronger-planner/qwen14-selection-exact-reading.json` and
`artifacts/stronger-planner/qwen14-selection-warehouse.json`.

The warehouse result proves per-candidate routing, not good model ranking. Its
two proposed reasons were generic, and local smoke-training checkpoints were
eligible alongside pretrained models. Training provenance and limitations need
to inform future proposals; independent reviewed evaluations remain necessary.
These two targeted cases do not replace the retained broader planner failures.
