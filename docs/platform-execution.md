# Saved plans and execution evidence

The planner proposes typed candidate workflows. Before the first compile or
preview, the engine saves an immutable BuildPlan revision with the goal, source
snapshot, skill hashes, candidate specifications, required capabilities,
experiments, metrics, stop conditions and human checkpoints. A separate executor
reads that stored revision; model prose and Markdown cannot grant tool authority.
Build already authorizes bounded preview work, so publishing a plan does not add
an approval dialog. Reviewed labels, training, recorded operation and delivery
retain their existing human gates.

ExecutionRun tracks execution separately from immutable plan content. The
existing durable call IDs produce append-only ToolEvent starts and finishes,
with input/output Artifact references, actual timing, errors and model identity.
Unknown monetary costs stay null. EvaluationReport records refer to the actual
captured evaluation, not a planner's claimed score. Replay reads these saved
objects and never reexecutes a tool.

The executor checks the plan hash, source/data/model snapshot, compiled candidate
identity and the intersection of planned tools with coded phase authority.
Changes during execution invalidate the run. Authorized effects are recorded;
later experiments and human-reviewed data use a new immutable revision rather
than rewriting the old plan. Stopped workers expose interrupted actions; a read
or replay cannot restart them.

Public BuildStatus includes optional plan and execution plus chronological
tool_events. GET /projects/{id}/build/plan, /build/events, /build/artifacts and
/build/replay expose the same stored objects. GET /build/artifacts/{artifact_id}
returns typed JSON content for an existing artifact.

The current planner still proposes workflows through the installed typed
detector/count/reading contracts. This foundation separates and records that
proposal; it does not add new model adapters, provision models, or claim a new
language-quality benchmark. Installed but unchecked capabilities may enter a
bounded experiment; unavailable or unsupported capabilities are rejected before
inference. A completed preview is the evidence for that exact experiment.

Detector snapshots include existing weight/configuration hashes. Reading
snapshots include the native bridge digest and macOS/kernel identity. LLM event
identity is explicitly a reported model alias, not verified weight provenance.
Costs remain unknown unless measured. Preview artifacts retain captured JSON
results and project-media references; they do not duplicate the source pixels.
Superseded segments become stale, preserving their actual individual action
outcomes. Read-only replay validates saved content hashes without tool effects.

Verification includes real synthetic-detector MCP compile/preview/evaluation,
saved-plan ordering, changed goals/data/settings/models/regions, immutable
records, native reading identity, changed playbook hashes, interrupted actions,
read-only API parity and replay. The fixture at `artifacts/platform-fixture/`
is execution-contract evidence, not model accuracy or language-quality evidence.
