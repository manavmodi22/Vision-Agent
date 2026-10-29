# Conversational edits to an existing app

The existing graph is the source of truth. A local planner interprets a follow-up
into a bounded list of typed edits or at most three essential clarification
questions. It cannot emit replacement graphs, code, file paths, review approval,
training approval, or deployment approval. Exact legacy confidence/class commands
may retain their deterministic fast path, while the conversational interpreter
calls the configured local model after a known-capability preflight and never
falls back silently.

`await agent.refinement.interpret_refinement(prompt, settings, build_id,
candidate_index=0)` returns `RefinementDecision(source, message, questions, patches)`.
The interpreter reads the actual candidate graph, current goal, previous turns,
class vocabulary and saved zone IDs through MCP. Current field values permit
relative instructions such as changing a sample rate by half. A clarification
answer is interpreted together with its original request and the agent's question,
not as a new isolated goal. Missing target values or multiple plausible target
blocks produce a question; the agent does not invent a business threshold.

Supported edits remain bounded by existing implemented blocks: confidence;
explicit additive, removal, or replacement class changes; count-rule threshold
and duration; expected label text/match mode; sample FPS; and evaluation metric
or target. `block_id` can disambiguate an existing block, and explicit scope can
select a candidate or all alternatives. Goal edits default to all alternatives;
confidence retains selected-candidate behavior. A multi-edit request becomes one
atomic batch, preserving unrelated graph fields and annotation data. Expanding
class coverage requires fresh human review.

Explicit email/webhook/MQTT delivery actions pause the entire compound edit before
model interpretation or graph changes. The question directs users to separate
webhook/MQTT destination setup and approval in Alerts; this editor does not send
email. The decision is marked `source=capability_guard`, with no invented model
call. Object names and quoted reading literals remain valid, and an explicit
vision-only answer can withdraw delivery setup. The MCP mutation boundary repeats
the check against the saved user request, including previously captured decisions.
This is a bounded check for known delivery actions, not a general natural-language
capability classifier or evidence of improved model understanding.

The local model has a 60-second per-request deadline within the unchanged
90-second overall refinement limit, at most two output retries, and bounded context.
Every actual model attempt is persisted through the build MCP capture tools and
exported as a local OTel span, including invalid outputs and validation retries.
The validated decision is also captured before execution. The existing build
fingerprint detects edits to the graph, samples, ontology or holdout during
interpretation. The engine revalidates the whole batch, compiles and previews all
affected candidates, then commits only against unchanged source evidence.

Deterministic schema/guard/engine tests and live language-model benchmarks are
reported separately. Root owns the live 20-plus-case brief/refinement benchmark
and native UI validation. A syntactically valid patch is not proof that a model
understood an instruction; the live benchmark must check exact intended fields,
unchanged graph fields, clarification, and actual model traces.

Execution uses the selected candidate for confidence edits by default and every
alternative for goal edits. A count rule or label match may be inserted only
after one unambiguous existing count or reading branch, using existing supported
block types. Class removal never deletes ground-truth boxes or ontology IDs.
When new classes enter the detection scope, existing boxes are retained and
review flags are reset so prior review cannot authorize the expanded task.
Comparison also requires equivalent class/zone/event-rule scope, the same metric,
target, and held-out dataset; a divergent alternative produces a clarification.

The native build flow now resumes from a `define_zones` checkpoint only after
confirmed region geometry exists, retaining the original request. Geometry input
does not spend the business-question budget. A target-miss deployment override
still requires the existing human approval API and reason; Continue checks its
current selected-candidate evidence before any recorded run.

Limits: this is a bounded editor for implemented detector/count/text blocks, not
arbitrary code generation. Counts aggregate the selected classes; it does not
infer unique-object tracking or silently create class-specific branches. Temporal
rules are executable, but existing box/count/text evaluation metrics do not
establish the correctness of business alerts. The configured small local model
can misunderstand language; captured output validation, at most two retries,
clarification, and explicit errors bound that risk. No other model or authored
preset silently substitutes for a failed conversational interpretation.

Verification and retained failures are documented in [refinement-quality-report.md](refinement-quality-report.md).
