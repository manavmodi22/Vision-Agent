"""Apply a branch-local transform edit without changing inference or outputs."""
from typing import cast

from pydantic import JsonValue

from spec.models import BlockSpec, PipelineSpec
from spec.preprocessing import preprocessing_target
from spec.refinement import RefinementPatch


def apply_preprocessing(candidate: PipelineSpec, patch: RefinementPatch) -> None:
    if patch.kind not in {"crop", "resize"}:
        raise ValueError("Expected a crop or resize refinement")
    target = preprocessing_target(candidate, patch.kind, patch.block_id)
    nodes = {block.id: block for block in candidate.blocks}
    consumer = nodes[target.consumer_id]
    params: dict[str, JsonValue] = ({"box": cast(JsonValue, patch.crop_box)} if patch.kind == "crop"
                                  else {"width": patch.width, "height": patch.height})
    if target.transform_id and all(nodes[target.transform_id].params.get(key) == value
                                   for key, value in params.items()):
        return

    def identifier(kind: str) -> str:
        prefix, suffix = "refined_" + kind, 1
        name = prefix
        while name in nodes:
            name, suffix = f"{prefix}_{suffix}", suffix + 1
        return name

    if target.transform_id is None:
        added = BlockSpec.model_validate({"id": identifier(patch.kind), "type": patch.kind,
            "params": params, "in": {"image": consumer.inputs["image"]}})
        candidate.blocks.insert(candidate.blocks.index(consumer), added)
        consumer.inputs["image"] = f"${added.id}.image"
    elif not target.copy_path:
        nodes[target.transform_id].params.update(params)
    else:
        connection = nodes[target.transform_id].inputs["image"]
        for old_id in target.path:
            clone = nodes[old_id].model_copy(deep=True)
            clone.id = identifier(clone.type)
            clone.inputs["image"] = connection
            if old_id == target.transform_id:
                clone.params.update(params)
            nodes[clone.id] = clone
            candidate.blocks.insert(candidate.blocks.index(consumer), clone)
            connection = f"${clone.id}.image"
        consumer.inputs["image"] = connection
