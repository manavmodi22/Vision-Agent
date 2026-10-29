+++
format = "visionapp.skill.v1"
id = "detection"
title = "Detection, counting and visual defect review"
task_types = ["detection"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Select for object detection/counting or the pallets/damage use cases."
required_inputs = ["Representative images","Requested classes","Confirmed polygons when the goal names regions"]
allowed_tools = ["blocks_list","block_schema","dataset_context","detect_open_vocab","pipeline_validate","pipeline_run","suggest_labels","build_prepare_review","build_propose_labels","eval_create","eval_run","build_context","build_train","train_status","review_queue"]
output_artifacts = ["Detection pipeline candidate","Bounding-box proposals","Detection or count evaluation"]
validation_recipe = ["Match predictions to reviewed boxes with declared IoU","Report precision, recall and count error with failed images","Use scene-disjoint holdouts for promotion, not adjacent frames alone"]
failure_modes = ["Unknown class vocabulary","Unconfirmed regions","Small or occluded objects","Subjective damage labels"]
version = "1.0.0"
+++

# Detect and count actual objects
Choose only installed, compatible capabilities for experiments. Open-vocabulary proposals can initialize labels; they are not ground truth. Use the saved ontology exactly. Keep manual corrections and reviewed rows.

Counting defaults to count error; detection or defect work measures precision and recall. Damage is subjective: define visible positive and negative examples with reviewed labels before claiming accuracy. A VLM judgement is a hypothesis that must be scored.

Use confirmed region geometry when requested. Never invent lanes or their capacity. A pure count needs no event trigger. Preserve an explicitly requested count comparison, hold time and evidence behavior.

Compare alternatives on the same objects, regions and holdout. Specialize a detector only after the required data and approval gates. A completed training job is not a promotion.

## Examples
- "Count pallets inside lane A": ask to draw A if no confirmed polygon exists; do not count the whole frame instead.
- "Alert when a lane is full": ask for capacity if absent.
- "Find damaged cartons": propose boxes for review and a measurable defect test; never claim the public forklift sample validates damage.
