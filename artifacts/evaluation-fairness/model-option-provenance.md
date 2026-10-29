# Give model choices their training context

Source-only follow-up on frozen `d403`. Root reported the actual warehouse gate
completed in 87.423 seconds with one LLM call, two real model routes, common
count-MAE target 0.5/confidence 0.2, and no recorded events. Both choices had
generic identical reasons. That is routing evidence, not a demonstration of
useful model selection or measured model quality. This audit did not rerun it.

## Manifest observations

Read directly from `~/Library/Application Support/VisionApp/models/<id>/manifest.json`:

| Field | `local-detector-rtdetr-prior001-20261028` | `local-ssdlite-7dcfc58e1c6e` |
|---|---|---|
| Adapter / classes | RT-DETRv2 / forklift, person | SSDLite / forklift, person |
| Initialization evidence | Base `rtdetr-v2-r18`; upstream revision and base-weight SHA256 recorded; `person` listed as preserved class | No base model; explicit warning says initialized from scratch. The SSDLite trainer uses no pretrained model/backbone weights in this path |
| Training recorded | 10 samples, 10 completed epochs, 50 optimizer steps, MPS | 10 samples, 1 completed epoch, 5 optimizer steps, CPU |
| Evidence limits recorded | Held-out scoring still required; scene/camera/time independence not established | Held-out scoring/approval not established; scene independence not verified; explicit small-training-set warning |
| Evaluation evidence in manifest | Evaluation dataset hash; no scored result or approval reference | Evaluation dataset hash; no scored result or approval reference |

The current trainer requires reviewed examples, but this read-only audit did not
reopen the training datasets or verify the histories independently. The manifest
facts are recorded provenance. An evaluation hash identifies data, not an actual
score. Results may exist elsewhere; no result is linked to these planning options.
Training losses were recorded but are not comparable quality scores across these
architectures. Neither manifest declares whether this is an engineering test
asset or a user model. Five optimization steps establish some training, so it
would be inaccurate to call SSDLite entirely uninitialized. Pretrained
initialization alone cannot establish that another candidate will perform better.

A subsequent artifact lookup found
[`rtdetr-pretrained-specialization.json`](../vision-verification/rtdetr-pretrained-specialization.json):
it names the RT-DETR checkpoint and matching training/evaluation dataset hashes,
reports recall 0.7732 against target 0.8 (`passed=false`) and count MAE 14.2 on ten
images, and explicitly limits its claim to synthetic, correlated frames. This
historical result is not linked into the catalog. Current checkpoint-weight
correspondence was not reverified in this audit, and the earlier task/threshold
differs from the new warehouse request. It is useful cautionary provenance, not
a current-project score. The root's observed repeated SSDLite confidence values
similarly warrant investigation but do not establish its original use purpose.

## Minimal metadata enrichment

Extend `PlanningModelOption` with an optional, bounded `training_provenance`
object and `evaluation_evidence` summary, sourced from the validated manifest and
existing recorded reports. Preserve legacy saved options/replay semantics.

```text
training_provenance:
  origin: upstream_pretrained | locally_trained | system_framework | synthetic | unknown
  initialization: pretrained_finetune | random | not_applicable | unknown
  training_state: untrained | optimization_completed | unknown
  use_scope: upstream_baseline | user_candidate | engineering_smoke | unknown
  use_scope_evidence_ref: opaque identifier|null
  base_model_id: string|null
  training_samples: int|null
  epochs_completed: int|null
  optimizer_steps: int|null
  preserved_classes: string[]
  provenance_scope: manifest_recorded | linked_training_run
  limitation_codes: string[]
evaluation_evidence:
  status: none_attached | different_scope | current_scope
  report_refs: opaque identifiers[]
  scope_match: task/data/weights identity result, when a report is attached
```

The full captured artifact already retains manifest hashes; keep upstream hashes,
dataset hashes, licenses and report details there. The compact model prompt needs
the initialization, sample/step counts, preserved classes, evidence status and
short coded limitations. Include these instead of only generic `unchecked`,
within the existing context budget. Do not send arbitrary manifest prose as tool
authority. Unknown fields stay unknown; do not infer fine-tuning success or scene
independence. `none_attached` means unavailable to this decision, not never tested.

Keep callable readiness separate from **default selection eligibility**. A
checkpoint can execute yet be inappropriate as an unqualified default for a
generic user goal. Proposed explicit policy:

| Provenance | Default experiment policy |
|---|---|
| `engineering_smoke`, or explicitly `untrained` | Exclude from generic-user candidate selection and report the reason. Keep visible in the catalog for an explicitly requested engineering experiment. |
| `user_candidate`, with recorded training lineage | Eligible for a compatible bounded comparison; expose missing or out-of-scope evaluation. Do not exclude merely because it is local or small. |
| `upstream_baseline`, trusted source/weights | Prefer as a baseline when it covers the actual task and has a captured successful adapter smoke. An installed but unchecked adapter first needs its bounded validation experiment. This is provenance preference, not a quality guarantee. |
| Unknown scope or initialization | Preserve `unknown`; do not present it as a recommended specialized detector ahead of a compatible proven baseline. Retain it as an explicit experimental choice with visible limitations. If the requested comparison lacks enough supported defaults, state that blocker instead of silently filling slots with unknown checkpoints. |

Scope must be recorded by the training/registration caller with its evidence
reference. Test/evaluation harnesses should register `engineering_smoke`; ordinary
user-approved training should register `user_candidate`. Existing models need
an evidence-based registration update; filenames, architecture, low step counts
and suspicious predictions alone must not assign test purpose. These inspected
legacy manifests therefore remain unknown unless their linked run provenance is
confirmed. Do not mutate or remove the files during migration.

The capture should expose both compatibility and this selection policy/reason.
The executor validates the selection mode bound to the user's request; the LLM
cannot promote an excluded engineering asset by asserting it is user-approved.
Ask the planner to explain the comparison hypothesis, without turning provenance
into a quality ranking. Explicitly requested experimental models stay usable.
Never replace a user's requested class with a pretrained model's narrower class
set; for example, a closed vocabulary missing forklift cannot be a substitute.

## Acceptance checks for the next change

* The two inspected manifests produce distinct initialization/training summaries;
  they remain eligible and retain exact class vocabulary.
* A manifest evaluation hash alone yields `none_attached`, never a passed score.
* A matched report requires current weights, dataset and task scope; stale or
  unrelated reports cannot become `current_scope` evidence.
* Legacy/unknown lineage stays unknown, and a small sample count does not cause
  silent exclusion or an invented universal quality threshold.
* A model explicitly marked `engineering_smoke` is omitted from generic goal
  choices with a recorded reason, but remains catalog-visible and available for
  an explicit experiment. A model with the word “smoke” only in its filename is
  not classified from that name.
* A user-trained checkpoint retains eligibility and its evidence limitations.
  Unknown lineage is not silently promoted ahead of a compatible baseline, and
  absent baseline class coverage causes a clear blocker rather than substitution.
* A captured options snapshot includes the facts supplied before the LLM call;
  metadata edits invalidate the selected receipt before inference. Legacy replay
  does not reload new provenance and attribute it to an older decision.
* A later live gate checks whether the planner uses the differences meaningfully.
  Contract tests alone cannot establish useful selection.

Relevant source: `engine/models/local_manifest.py`, `engine/train/rtdetr.py`,
`engine/train/__init__.py`, `engine/models/ssdlite.py`,
`engine/platform/planning_options.py`, and the compact projection in
`agent/planner.py:107`. No runtime code was changed for this proposal.
