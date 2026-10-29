+++
format = "visionapp.skill.v1"
id = "tracking"
title = "Temporal identity and spatial events"
task_types = ["tracking"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Select for tracking identities, line crossing, trajectories or dwell."
required_inputs = ["Timestamped video or live frames","Confirmed line or zone geometry","Supported temporal blocks","Reviewed temporal event examples"]
allowed_tools = ["blocks_list","block_schema","dataset_context","pipeline_validate","pipeline_run","eval_create","eval_run","review_queue"]
output_artifacts = ["Tracked trajectories","Temporal event evidence","Temporal acceptance report"]
validation_recipe = ["Preserve source timestamps and sequence order","Measure identity continuity and event correctness when implemented","Verify reset behavior across clips and reconnects"]
failure_modes = ["Missing tracking block","Frame counts misrepresented as unique objects","Identity switches","Undefined dwell or crossing direction"]
version = "1.0.0"
+++

# Track across time rather than counting frames
Check the actual temporal block catalog. Frame-wise detection counts do not establish unique object counts, dwell or line crossing. Do not substitute count thresholds for an unavailable tracking capability.

Use confirmed geometry and source timestamps. Define direction, hold/dwell semantics, clip boundaries and reconnect behavior. Keep IDs scoped to the tracking session and expose identity uncertainty in evaluation.

## Examples
- "Count unique forklifts crossing this line": requires tracking, line geometry and crossing direction; repeated detections are not unique crossings.
- "Flag a pallet that stays for ten minutes": requires a timestamped dwell implementation and retained identity, not ten frames with a box.
