"""Pure branch targeting for bounded crop/resize refinements."""
from dataclasses import dataclass
from typing import Literal

from spec.models import BlockSpec, PipelineSpec

IMAGE_CONSUMERS = frozenset({"detect", "detect_open_vocab", "ocr", "barcode", "vlm_judge"})
TRANSFORMS = frozenset({"crop", "resize"})


@dataclass(frozen=True)
class PreprocessingTarget:
    consumer_id: str
    transform_id: str | None
    path: tuple[str, ...]  # Existing transform through downstream transforms, excluding consumer.
    copy_path: bool
    input_is_cropped: bool


def _owner(reference: str) -> str:
    if not reference.startswith("$") or reference.count(".") != 1:
        raise ValueError("The existing image connection is invalid; repair the workflow first")
    return reference[1:].split(".", 1)[0]


def image_chain(consumer: BlockSpec, nodes: dict[str, BlockSpec]) -> list[str]:
    """Return preprocessing ancestors nearest first; reject a malformed chain."""
    result: list[str] = []
    current = consumer
    while True:
        reference = current.inputs.get("image", "")
        owner = _owner(reference)
        if owner not in nodes or owner == consumer.id or owner in result:
            raise ValueError("The existing image path is missing or cyclic; repair the workflow first")
        current = nodes[owner]
        if current.type == "frame_sample":
            if reference != f"${owner}.frame":
                raise ValueError("The existing frame source port is invalid")
            return result
        if current.type not in TRANSFORMS:
            raise ValueError("Only crop and resize preprocessing can be refined on this image path")
        if reference != f"${owner}.image":
            raise ValueError("The existing preprocessing output port is invalid")
        result.append(current.id)


def preprocessing_target(candidate: PipelineSpec, kind: Literal["crop", "resize"],
                         block_id: str | None) -> PreprocessingTarget:
    nodes = {block.id: block for block in candidate.blocks}
    if len(nodes) != len(candidate.blocks):
        raise ValueError("The existing graph has duplicate block IDs")
    consumers = [block for block in candidate.blocks if block.type in IMAGE_CONSUMERS]
    explicit_transform: str | None = None
    if block_id is not None:
        selected = nodes.get(block_id)
        if selected is None or selected.type not in IMAGE_CONSUMERS | {kind}:
            raise ValueError(f"Select an existing {kind} transform or image-consuming inference block")
        if selected.type == kind:
            explicit_transform = selected.id
            consumers = [consumer for consumer in consumers if selected.id in image_chain(consumer, nodes)]
            if len(consumers) > 1:
                raise ValueError("This transform is shared; choose the detector or reader branch to change")
        else:
            consumers = [selected]
    if len(consumers) != 1:
        raise ValueError("Choose one existing detector or reader block; the preprocessing target is missing or ambiguous")
    consumer = consumers[0]
    chain = image_chain(consumer, nodes)
    matches = [identifier for identifier in chain if nodes[identifier].type == kind
               and (explicit_transform is None or identifier == explicit_transform)]
    if len(matches) > 1:
        raise ValueError(f"This branch has multiple {kind} transforms; name the existing transform to update")
    if not matches:
        return PreprocessingTarget(consumer.id, None, (), False, any(nodes[name].type == "crop" for name in chain))
    transform = matches[0]
    index = chain.index(transform)
    path = tuple(reversed(chain[:index + 1]))
    permitted = {*path, consumer.id}
    shared = any(_owner(reference) in path for node in candidate.blocks if node.id not in permitted
                 for reference in node.inputs.values())
    return PreprocessingTarget(consumer.id, transform, path, shared,
                               any(nodes[name].type == "crop" for name in chain[index + 1:]))
