# Native agent platform foundation

The Agent remains the primary workspace: a goal and examples on the left, actual
application output on the right. A saved `BuildPlan` appears prominently above
the conversation as soon as the server returns it. The card shows candidate
names, metric directions and targets, plan revision, and the separate execution
state. **Review plan** opens a read-only sheet; it does not authorize or initiate
execution. Build already authorizes bounded planning and preview. Existing label,
training, deployment and external-delivery approvals remain unchanged.

When supplied by the server, each candidate shows its **model to test** and
**proposed reason** in the plan summary and details. These are planner proposals,
not measured quality claims or an approved winner. The details preserve adapter,
capability and options-snapshot identity, and can inspect the saved model-options
artifact through the existing read-only artifact API. Historical plans without
these optional fields remain readable and do not acquire invented rationales.

The composer and current human action stay fixed below the left conversation
scroll. The plan summary omits the duplicated goal paragraph. Agent activity
defaults to the current active call or latest actual event; the full chronological
trail is available in an expandable disclosure.

Preview correction, evaluation-failure correction and the label-review checkpoint
open the existing annotation workspace in a contextual sheet. Its full canvas,
filmstrip and inspector need more width than the narrow right pane, so the sheet
returns to the unchanged Agent conversation. It shares the persistent dataset
store, autosave and conflict behavior with expert Annotations. Closing explicitly
flushes the current draft; save conflicts keep the sheet open. Review state is
never granted automatically. Current-frame correction requires an exact dataset
image match; the review checkpoint selects an unreviewed example first.

With multiple candidates, an idle-only preview selector requests an actual sample
run for the inspected candidate. The approval candidate remains unchanged. Old
boxes are cleared before inference, and each result is accepted only for the same
project, candidate specification and request identity. The displayed workflow
snapshot follows the inspected result; late responses cannot replace a newer
selection. Successful sample previews clear recorded/previous-result flags.

For event workflows, the output pane shows the selected frame's actual emitted
event count and recorded type, message, reason, comparison or count-rule fields.
No event is a sample outcome, not a correctness score. Preview results explicitly
state that no events were recorded; successful approved operation results are
tracked separately with event recording enabled; the per-frame count indicates
whether an event was emitted. Reading workflows emphasize
text output rather than an irrelevant empty object-detection message.

The plan sheet exposes assumptions, candidate specifications, capability
requirements, bounded experiments, stop conditions, human checkpoints, versioned
playbook hashes, and the dataset/model/settings snapshot. Capability links open
the corresponding catalog entry. A mismatched execution plan ID/hash is visible.

## Capability truth

The global Capabilities screen reads `GET /capabilities` and is available before
a project exists. Search and filters distinguish tools/models and installed,
available-to-install, and unsupported entries. Installation is separate from
readiness. A capability appears ready only when the server reports installed,
implemented, installation-ready, callable, and readiness `ready` together. Local
weights with unchecked inference remain visibly unverified. Installed,
installation-ready implementations remain explicitly eligible for bounded
validation without claiming a successful inference receipt. Missing prerequisites
and unsupported implementations remain ineligible. Requirements,
installation instructions, reasons, license status, provenance, evidence scope,
side effects, dependencies, and schemas are inspectable. There is no install
button because this API does not implement provisioning.

## Recorded execution

The chronological action timeline uses `ToolEvent.sequence`, never a simulated
phase list. Started and terminal records display their actual stage, time,
duration, model identity, error and input/output artifact references. Only an
unmatched start in a running build gets a spinner. Earlier phase logs remain
available in a separate collapsed status history. Empty event lists make no
execution claims.

Artifact inspection resolves opaque IDs through the project-scoped API and
shows the saved JSON and recorded hash. It does not interpret IDs as paths or
execute artifact content. Page loads only read. Artifact errors remain visible
with an explicit retry control; engine connection guards remain active.

## Compatibility and checks

New build fields are optional for historical saved responses. Optional OCR
character/word error rates are displayed only when reported; values above 100%
are retained, and historical missing values do not become zero. The text accuracy
gate is described as normalized per-image text-list equality.

Native source identity mirrors Python's package order and jointly sorted Python
and `agent/skills/packages/**/*.md` paths. Native golden checks cover the unchanged
Python-only hash, a packaged Markdown addition/edit, and excluded documentation.
Contract checks cover capability readiness, nullable evidence, plan provenance,
human gates, sequence ordering, terminal failures, opaque artifact references,
and optional OCR rates. These deterministic checks do not claim model inference
or new adapter support. Root-owned native UI acceptance verifies the rendered
integration separately.

Validation on 2026-10-28: debug and release SwiftPM builds succeeded. Both binaries
passed 138 deterministic checks, plus ten server-payload decoding checks: the
73-entry local capability catalog, a persisted revision-2 fixture build with ten
MCP events, all seven artifact contents, and the actual two-detector warehouse
planning probe with per-candidate model proposals. The resulting 148-check reports and
binary/payload hashes are in `artifacts/native-platform-validation.json`. No LLM
requests, server restarts, deployment, packaging or UI automation ran in this
native validation.
