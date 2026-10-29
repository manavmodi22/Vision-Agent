# ADR 0004: default to pretrained RT-DETRv2 specialization

Accepted 2026-10-28. Owner: CV core.

A short from-scratch SSDLite run demonstrated optimization but produced unusable
held-out predictions. Users need custom vision models, so the default training
path now starts from the publisher's permissive RT-DETRv2 R18 checkpoint. D-FINE
small is also publisher-labelled Apache-2.0, but RT-DETRv2 was selected after an
actual MPS training step succeeded with the installed Transformers version.

The existing `train_detector` signature remains intact. A missing base model
selects pretrained RT-DETRv2; a local base resumes its recorded backend. Existing
SSDLite manifests keep working. New manifests extend optional lineage fields and
record the backend, code/weight terms, checkpoint revision and exact weight hash.

Classification remapping must preserve known rows and use a low object prior for
new classes. Without this, the default two-class initialization gives unmatched
queries approximately 0.5 confidence and floods proposals. This is a correctness
fix, not an empirical accuracy claim. New heads still require sufficient reviewed
examples and optimization, and the unchanged held-out evaluation gate decides
whether a candidate is usable.

Validation: actual MPS optimizer step, full train/save/reload/held-out path, unit
checks for class-row transfer and unseen-class priors, older backend compatibility,
and explicit model availability/license checks. Dataset provenance and correlated
holdout limitations remain visible in verification artifacts.
