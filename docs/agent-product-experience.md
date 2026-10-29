# Product contract: describe the outcome, agent builds the application

The user's correction is authoritative: this is a vision application builder
operated through an agent. Dataset annotation, graph editing, model configuration,
and evaluation are capabilities the agent uses or opens for a specific correction.
They are not a sequence of expert screens the user must learn to operate.

## Reference inspected

The public [Roboflow Agent presentation](https://roboflow.com/agent) starts with an
outcome prompt. The published [video-task walkthrough](https://roboflow.com/blog/annotating-video#how-to-use-the-roboflow-agent-for-video-tasks)
shows the actual product screens: a goal composer at home, persistent conversation
on the left, a generated workflow or preview on the right, and contextual training
and correction inside that interaction. These public screenshots were inspected;
they are interface references, not an independent validation of vendor performance.

## Required main journey

1. Enter a goal and attach representative images/video. A name, class list, model
   choice and hand-built graph are not prerequisites. The app creates the project.
2. The agent asks only essential business questions, chooses available models and
   defaults, compiles a typed pipeline, runs it, and shows the real result. The
   conversation and actual work log remain visible throughout.
3. The agent proposes labels where evaluation needs ground truth. The user reviews
   and corrects that proposal in context, then returns to the same build. Model
   proposals never silently become verified labels.
4. The agent evaluates candidates, explains the measured result, and proposes a
   bounded improvement when needed. A user-approved training job returns its
   result to the same build and is evaluated against the same holdout.
5. The user approves the concrete application before recorded runs or external
   alerts. A working preview is available before that gate. Natural-language
   refinements update the current application and invalidate stale test evidence.

## Acceptance evidence

Use a plain-language goal with the public NVIDIA sample data, through the native
UI. Verify actual tool execution, visible preview, persisted generated pipeline,
automatic label proposals, and a precise review request. Then exercise resume on
reviewed fixtures through evaluation and the separate explicit deployment gate.
Verify that a refinement retains the current application's unrelated settings.
There must be no fabricated tool steps, passing scores, reviewed labels, or
production-ready claims. The application must open to the agent, not the dataset
grid or block editor. Expert tools remain available under secondary controls.

## Latest interaction evidence

The packaged `d42048535b5d` foundation was exercised from native Home with the
exact goal `Read printed labels and create a local event only when the text
exactly equals "ABC-990".` One actual local Qwen call produced the workflow.
Apple Vision read both generated sample images; the exact string emitted one
preview event and the longer string emitted none. No event was recorded and no
evaluation or deployment approval was created. The two samples are controlled
software/semantic checks, not representative OCR validation.

The composer stays outside the conversation scroll, and current activity is
separate from the expandable raw trace. Preview now displays the actual rule
outcome. `Correct this image` opens the persistent annotation workspace and
returns to the same conversation. An expected-text correction was saved through
that UI while its review checkbox remained off. Evidence and screenshots are in
`artifacts/agent-experience/platform/`.

This acceptance also exposed two functional gaps: the catalog initially confused
unchecked capabilities with ineligible ones (corrected and rechecked), and Apple
Vision read the leading Latin X as a Cyrillic character on one sample. Explicit
reading-language policy and evaluation identity are being corrected separately.
The foundation still uses an injected detector policy and generic host-authored
plan steps; the newer per-candidate selection work must pass its own integration
and live-model gates before replacing the packaged build.
