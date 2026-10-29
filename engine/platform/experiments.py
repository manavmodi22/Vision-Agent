"""Host-authored experiment policy for the task that is actually authorized."""
from agent.machine import TOOLS, Phase
from spec.models import PipelineSpec
from spec.platform import HumanCheckpoint, PlanExperiment


def experiment_policy(candidates: list[PipelineSpec], phase: Phase) -> tuple[list[PlanExperiment], list[HumanCheckpoint]]:
    detector = any(block.type in {"detect", "detect_open_vocab"} for spec in candidates for block in spec.blocks)
    if phase == Phase.SPECIALIZE and not detector:
        raise ValueError("Detector training is not an experiment for a reading-only workflow")
    names = {
        Phase.PLAN: ("Apply requested typed edits and preview affected candidates.", {"build_refine"}),
        Phase.COMPILE: ("Compile every candidate and preview up to five samples.", {"pipeline_validate", "pipeline_run"}),
        Phase.EVALUATE: ("Prepare the review set, then measure candidates once its labels are reviewed.",
                         {"build_context", "build_prepare_review", "build_freeze_evaluation", "eval_run", "pipeline_run"} | ({"build_propose_labels"} if detector else set())),
        Phase.SPECIALIZE: ("Use the explicitly approved detector-training budget, then compare results.",
                           {"build_train", "build_context", "build_freeze_evaluation", "eval_run", "pipeline_run"}),
        Phase.OPERATE: ("Run the candidate bound to current human deployment approval.", {"build_operate"}),
    }
    stages = [phase] + ([Phase.EVALUATE] if phase in {Phase.PLAN, Phase.COMPILE} else [])
    experiments = [PlanExperiment(id=stage.value, phase=stage.value, description=names[stage][0],
        allowed_tools=sorted(names[stage][1] & TOOLS[stage]), candidate_indices=list(range(len(candidates)))) for stage in stages]
    checkpoints = []
    if phase != Phase.OPERATE:
        checkpoints.append(HumanCheckpoint(id="labels", phase="evaluate",
            description="Before scoring, review any unreviewed labels in the chosen evaluation set."))
        checkpoints.append(HumanCheckpoint(id="deployment", phase="operate",
            description="Choose independent acceptance for promotion, or explicitly approve a bounded local-only trial."))
    if phase == Phase.SPECIALIZE:
        checkpoints.append(HumanCheckpoint(id="training", phase="specialize",
            description="This training experiment requires the explicit, bounded human approval already requested."))
    if phase == Phase.OPERATE:
        checkpoints.append(HumanCheckpoint(id="deployment", phase="operate",
            description="Execution requires current human approval for this exact evaluated candidate."))
    return experiments, checkpoints
