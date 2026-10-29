"""Ground truth for the detection branch exposed by FrameResult.detections."""
from __future__ import annotations

from dataclasses import dataclass

from engine.blocks.params import DetectParams
from engine.blocks.registry import REGISTRY
from engine.blocks.spatial import assign_zones
from engine.compiler import CompiledPipeline, parse_reference
from spec.models import Detection, Zone


@dataclass(frozen=True)
class DetectionScope:
    classes: frozenset[str]
    zone_stages: tuple[tuple[Zone, ...], ...] = ()

    @property
    def zone_ids(self) -> list[str]:
        # Each filter replaces zone assignments, as it does in the executor.
        return [zone.id for zone in self.zone_stages[-1]] if self.zone_stages else []

    def ground_truth(self, detections: list[Detection]) -> list[Detection]:
        selected = [item.model_copy(update={"zone": None}) for item in detections
                    if item.label in self.classes]
        for zones in self.zone_stages:
            selected = assign_zones(selected, list(zones))
        return selected


def detection_scope(compiled: CompiledPipeline) -> DetectionScope:
    """Trace the final detection-producing block, following only its ancestors."""
    outputs = [block for block in compiled.blocks
               if "detections" in REGISTRY[block.type].outputs.values()]
    if not outputs:
        return DetectionScope(frozenset())
    nodes = {block.id: block for block in compiled.blocks}
    current = outputs[-1]
    zone_stages = []
    while current.type == "zone_filter":
        zone_stages.append(tuple(compiled.zones[current.id]))
        owner, _ = parse_reference(current.inputs["dets"])
        current = nodes[owner]
    params = compiled.params[current.id]
    if not isinstance(params, DetectParams):
        raise ValueError("The final detection output has no supported detector ancestor")
    return DetectionScope(frozenset(params.classes), tuple(reversed(zone_stages)))
