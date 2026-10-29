# Agent and MCP design

Owner: agent/backend engineer. Contract: `docs/architecture.md`, spec 0.1.

## Interfaces and ownership

`agent.machine.AgentState` owns phase, budgets and evidence references. Its
transitions are explicit application decisions. Model text cannot transition a
project, approve deployment, change alert destinations or delete data.
`authorize_tool(name)` checks phase, elapsed time and call budget before a tool
call. Training is additionally limited by a recorded training-minute budget.

`agent.planner.plan(brief, source_path, settings)` returns a typed `PlanResult`.
The model emits a compact `PlanDecision` choosing authored patterns and bounded
parameters. `compile_decision` deterministically expands them to PipelineSpecs.
This is the normal architecture, not an offline fallback: successful planning
requires a real model decision, MCP compilation and a five-frame preview. A
count-only request does not invent a lane capacity or alert rule.
An additional deterministic completeness check rejects a count-only proposal
when the current user request explicitly asks for an alert, asking for lane
capacity instead. This check was added after a real local-model probe revealed
that the model could silently omit the requested alert. The persisted project
clarification count limits questions across turns to three.
It uses Pydantic AI's Chat Completions adapter with an explicitly configured local
OpenAI-compatible URL, model and two output validation retries. Native JSON
schema output constrains keys; the model server must support `response_format`
with `json_schema`. It never silently
substitutes a template or an internet model. A localhost connection failure or
unloaded model is a user-visible planning failure.

The planner has a genuine MCP stdio client. Block discovery and compiler
validation cross that boundary; the agent never imports the engine. MCP exposes
typed thin wrappers around engine APIs and `WorkspaceService`. MCP mutation
capabilities exclude human approval: deployment approval remains an app/API user
action. The subprocess uses the same project data directory.

`agent.templates.build_template(use_case, source_path, model)` constructs authored
patterns for pallets, damage, and labels. The UI must explicitly select template
mode. Its output is never evidence that a language model generated a pipeline.

State and budget models are JSON serializable. The service persists them inside
project records where appropriate; the agent performs no project file I/O. Skills
are small packaged strings supplied for the current use case, never arbitrary
instructions read from user media or external documents.

## Failure and acceptance rules

* A plan has at most three clarifying questions and one to three candidates, or
  questions with no candidates; no arbitrary code is an accepted output.
* A missing/changed spec or dataset invalidates evaluation and deployment gates.
* Passing metrics do not replace a human deployment click.
* Failed metrics need an explicit recorded override; an override does not imply
  model accuracy and cannot dispense with evaluation.
* A failed tool call consumes budget. A process restart never resets a persisted
  budget or carries stale approvals into a different spec.
* Unsupported operations return errors rather than fabricated progress.

Unit tests cover illegal transitions, stale evidence, budgets, tool whitelists,
planner URL validation and template construction. MCP integration tests perform
an actual stdio initialize/list/call cycle. `evals/warehouse_briefs.json` contains
24 cases for deterministic pattern/compiler regression. A separate live benchmark
requires a reachable model and records success, calls, latency and failures; it
must never be reported as passing when no local model was tested.
