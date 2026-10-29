+++
format = "visionapp.skill.v1"
id = "segmentation"
title = "Segmentation experiments and mask evaluation"
task_types = ["segmentation"]
phases = ["clarify","plan","compile","evaluate","specialize","deploy","operate"]
selection_rule = "Select when the user requests masks, segmentation or pixel-level outlines."
required_inputs = ["Representative images","Object or text/point prompts","Reviewed instance masks","A compatible implemented segmentation adapter"]
allowed_tools = ["blocks_list","block_schema","dataset_context","pipeline_validate","pipeline_run","eval_create","eval_run","review_queue"]
output_artifacts = ["Mask predictions with coordinates and provenance","Instance segmentation evaluation"]
validation_recipe = ["Require adapter contract and hardware smoke evidence","Compare mask IoU and instance metrics on the same reviewed data","Report mask errors by scale and occlusion"]
failure_modes = ["Missing adapter","Unproven Mac hardware support","Bounding boxes substituted for masks","No reviewed mask holdout"]
version = "1.0.0"
+++

# Produce and evaluate actual masks
Discover a compatible segmentation adapter before planning a callable experiment. A SAM family mention is not installation or hardware evidence. If local support is absent, identify that gap. A remote path requires an explicitly configured destination and data-transfer consent.

Preserve mask coordinate transforms, confidence and model provenance. A bounding box or colored overlay is not a segmentation mask. Do not fabricate masks from boxes or promote a segmentation model using a detection-only score.

## Examples
- "Outline each pallet": plan mask output only if a supported segmentation adapter exists; otherwise show the required capability.
- "Compare two mask models": use identical reviewed instance masks and report measured mask/instance errors, latency and resource use.
