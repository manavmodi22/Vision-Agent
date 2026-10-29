+++
format = "visionapp.skill.v1"
id = "alerting"
title = "Local events and configured delivery"
task_types = ["alerting"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Select for events, alerts, notifications or saved detection evidence."
required_inputs = ["Explicit event condition","Configured destination for external delivery","Human approval for recorded operation and external delivery"]
allowed_tools = ["blocks_list","block_schema","dataset_context","pipeline_validate","pipeline_run","build_context","events_query","report_make","build_operate","review_queue"]
output_artifacts = ["Local event rule","Approved delivery configuration reference","Delivery receipt or failure"]
validation_recipe = ["Check event threshold, polarity and duration","Preview must not send external messages","Verify idempotency and delivery receipts in approved operation"]
failure_modes = ["Missing destination","Partial compound edit","Retry duplicates","Preview mistaken for delivery"]
version = "1.0.0"
+++

# Separate event behavior from delivery configuration
A local event or saved crop can be part of a previewable application. External email, webhook or MQTT delivery additionally requires an implemented transport, configured destination and human approval. A model cannot invent recipients, credentials, approval or delivery receipts.

Preserve the entire compound request. If delivery setup is unsupported in the current edit path, ask for configuration without partially changing confidence or classes. An explicit later request to skip delivery may proceed with only the vision changes.

## Examples
- "Save a crop whenever a person appears": plan a local evidence event on the requested condition; no external destination is implied.
- "Raise confidence and email me": preserve current application until the delivery question is resolved.
- "Do not send email": do not interpret email as an object class or create an outbound action.
