+++
format = "visionapp.skill.v1"
id = "authoring"
title = "Describe, plan, execute and measure"
task_types = ["authoring"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Always load for a supported build phase; other playbooks add task-specific guidance."
required_inputs = ["The user's outcome","Imported media or an explicit request for source acquisition","Installed capability catalog"]
allowed_tools = ["blocks_list","block_schema","dataset_context","pipeline_validate","pipeline_run","build_context","build_prepare_review","build_propose_labels","eval_create","eval_run","train_status","build_train","review_queue","events_query","report_make","build_operate"]
output_artifacts = ["BuildPlan revision","ExecutionRun and action records","EvaluationReport"]
validation_recipe = ["Validate schema, inputs and capability readiness before execution","Preview actual samples; label proposals remain unreviewed","Compare compatible candidates on the same reviewed holdout"]
failure_modes = ["Missing capability or media","Changed data, model or plan revision","Exhausted budget or failed target"]
version = "1.0.0"
+++

# Build the requested vision application
Preserve the user's outcome, class names, spatial regions, thresholds and output semantics. Ask only for missing business meaning. Do not require a preset or a hand-built graph.

Save a typed, reviewable plan before executing candidate experiments. State data assumptions, capability requirements, metric targets, stop conditions and human checkpoints. A model may propose a step; the executor validates its authority and current inputs. Never execute free-form generated code.

Use the tool catalog as the executable boundary. A proposed adapter is not installed merely because a playbook mentions it. Preview results demonstrate execution, not accuracy. Show failed steps and their artifacts. Do not approve labels, training, recorded operation or external delivery from model prose.

## Examples
- "Count people in these images": discover detection, build a count preview, then request label review for measured count error.
- "Detect a new object class": retain the requested class and test an eligible open-vocabulary adapter; never silently map it to a different pretrained class.
- An unavailable capability: explain the missing adapter or data and preserve the current application.
