"""Exact per-block model binding checks, shared by saved-plan execution boundaries."""
from spec.models import PipelineSpec
from spec.planning import CandidateModelSelection, PlanningOptions


def validate_block_bindings(candidate: PipelineSpec, selections: list[CandidateModelSelection],
                            candidate_index: int, options: PlanningOptions | None = None) -> None:
    """Every composed inference block needs one exact, eligible saved binding."""
    bound = [item for item in selections if item.candidate_index == candidate_index]
    nodes = {block.id: block for block in candidate.blocks if block.type in {"detect", "detect_open_vocab", "ocr", "barcode"}}
    if len(bound) != len(nodes) or {item.block_id for item in bound} != set(nodes):
        raise ValueError("Composed model bindings must cover every inference block exactly once")
    for item in bound:
        assert item.block_id is not None
        block = nodes[item.block_id]
        task = "detection" if block.type in {"detect", "detect_open_vocab"} else block.type
        if options is not None:
            option = next((value for value in options.eligible_models if value.capability_id == item.capability_id), None)
            if (option is None or item.options_snapshot_id != options.snapshot_id or item.model_id != option.model_id
                    or item.adapter_id != option.adapter_id or task not in option.task_types):
                raise ValueError("Saved inference binding differs from its captured model capability")
        actual = block.params.get("model", "apple-vision" if block.type in {"ocr", "barcode"} else None)
        if actual != item.model_id:
            raise ValueError("The graph's model differs from its saved per-block selection")
