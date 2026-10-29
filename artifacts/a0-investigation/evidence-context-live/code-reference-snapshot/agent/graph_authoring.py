"""Reconstruct composed candidates from captured typed data, without tools or I/O."""
import json
from pathlib import PurePath

from pydantic import JsonValue

from agent.contracts import PatternChoice, PlanDecision, PlanResult
from agent.graph_structure import inputs, ordered_nodes
from agent.model_selection import selected_option
from spec.authoring import (
    BarcodeNode,
    CountNode,
    CropNode,
    DetectNode,
    GraphCandidate,
    GraphNode,
    MatchNode,
    OCRNode,
    ResizeNode,
    RuleNode,
    SampleNode,
    ZoneNode,
)
from spec.models import BlockSpec, PipelineSpec
from spec.planning import CandidateModelSelection, PlanningOptions


def model_choice(node: DetectNode | OCRNode | BarcodeNode, graph: GraphCandidate) -> PatternChoice:
    reading = not isinstance(node, DetectNode)
    return PatternChoice(use_case="custom", pipeline_type="detection" if isinstance(node, DetectNode) else node.type,
        objects=node.classes if isinstance(node, DetectNode) else [],
        min_confidence=node.min_confidence if isinstance(node, DetectNode) else 0.4,
        model_capability_id=node.model_capability_id, model_reason=node.model_reason,
        metric="text_accuracy" if reading else graph.metric,
        target=graph.target if not reading or graph.metric == "text_accuracy" else 0.95)


def objective_signature(graph: GraphCandidate) -> str:
    """Ignore generated names and model experiments; retain branch/behavior scope."""
    canonical: dict[str, JsonValue] = {}
    for node in ordered_nodes(graph):
        fields = node.model_dump(mode="json", exclude={"id", "model_capability_id", "model_reason", "min_confidence"})
        for name in ("image", "dets", "counts", "text", "event"):
            reference = fields.get(name)
            if isinstance(reference, str):
                owner, port = reference[1:].split(".")
                fields[name] = {"source": canonical[owner], "port": port}
        canonical[node.id] = fields
    return json.dumps({"metric": graph.metric, "target": graph.target,
        "nodes": sorted(json.dumps(value, sort_keys=True) for value in canonical.values())}, sort_keys=True)


def graph_model_selections(graphs: list[GraphCandidate], options: PlanningOptions) -> list[CandidateModelSelection]:
    if options.schema_version != "0.3":
        raise ValueError("Composed graphs require current captured reader/model options")
    if len({objective_signature(graph) for graph in graphs}) > 1:
        raise ValueError("Alternatives must preserve the same composed task, branch connections, event behavior and metric")
    selections = []
    for index, graph in enumerate(graphs):
        for node in ordered_nodes(graph):
            if isinstance(node, (DetectNode, OCRNode, BarcodeNode)):
                option = selected_option(model_choice(node, graph), options)
                selections.append(CandidateModelSelection(candidate_index=index, block_id=node.id,
                    capability_id=option.capability_id, model_id=option.model_id, adapter_id=option.adapter_id,
                    proposed_reason=node.model_reason, options_snapshot_id=options.snapshot_id))
    return selections


def _block(node: GraphNode, graph: GraphCandidate, options: PlanningOptions) -> BlockSpec:
    params: dict[str, JsonValue] = {}
    refs = {key: value[0] for key, value in inputs(node).items()}
    if isinstance(node, SampleNode):
        params, refs = {"fps": node.fps}, {"frames": "$inputs.source"}
    elif isinstance(node, CropNode):
        params = {"box": list(node.box)}
    elif isinstance(node, ResizeNode):
        params = {"width": node.width, "height": node.height}
    elif isinstance(node, (DetectNode, OCRNode, BarcodeNode)):
        model = selected_option(model_choice(node, graph), options).model_id
        if isinstance(node, DetectNode):
            params = {"model": model, "classes": list(node.classes), "min_conf": node.min_confidence}
        elif isinstance(node, OCRNode):
            params = {"model": model}
    elif isinstance(node, ZoneNode):
        params = {"zones": "zones/lanes.json", "include_ids": list(node.zone_ids)}
    elif isinstance(node, CountNode):
        params = {"include_unassigned": node.include_unassigned}
    elif isinstance(node, RuleNode):
        params = {"when": f"count {node.operator} {node.threshold}", "hold_s": node.hold_seconds}
    elif isinstance(node, MatchNode):
        params = {"expected": node.expected, "mode": node.mode, "emit": node.emit}
    return BlockSpec(id=node.id, type=node.type, params=params, **{"in": refs})


def compose_graph(graph: GraphCandidate, source_path: str, options: PlanningOptions) -> PipelineSpec:
    suffix = PurePath(source_path).suffix.lower()
    source_type = ("video_file" if suffix in {".mp4", ".mov", ".avi", ".mkv"} else
                   "image_file" if suffix in {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".bmp"} else "image_folder")
    return PipelineSpec.model_validate({"spec_version": "0.1", "name": graph.name,
        "inputs": {"source": {"type": source_type, "path": source_path}},
        "blocks": [_block(node, graph, options).model_dump(mode="json", by_alias=True) for node in ordered_nodes(graph)],
        "eval": {"set": "reviewed-v1", "metric": graph.metric, "target": graph.target}})


def graph_plan_from_context(decision: PlanDecision, brief: str, source_path: str,
                            context: dict[str, JsonValue] | None, options: PlanningOptions | None) -> PlanResult:
    from agent.graph_intent import validate_graph_intent
    from agent.graph_summary import describe_candidates

    if decision.questions:
        return PlanResult(message=decision.message, questions=decision.questions)
    if options is None:
        raise ValueError("Composed graphs require captured capability options")
    graph_model_selections(decision.graphs, options)
    validate_graph_intent(decision.graphs, brief, context or {})
    zones = [node for graph in decision.graphs for node in graph.nodes if isinstance(node, ZoneNode)]
    if zones and context is not None:
        raw_ids = context.get("saved_zone_ids", [])
        saved = {item for item in raw_ids if isinstance(item, str)} if isinstance(raw_ids, list) else set()
        missing = sorted({name for node in zones for name in node.zone_ids if name not in saved})
        if not context.get("zones_confirmed") or not saved or missing:
            return PlanResult(message="The workflow needs saved region boundaries before its spatial counts can run.",
                questions=["Mark and save " + (", ".join(missing) if missing else "the requested regions") + " on an example, then continue."],
                needs_zones=True)
    candidates = [compose_graph(graph, source_path, options) for graph in decision.graphs]
    transforms = any(isinstance(node, (CropNode, ResizeNode)) for graph in decision.graphs for node in graph.nodes)
    message = describe_candidates(candidates)
    if transforms:
        message += " Uses the crop/resize steps shown in the saved workflow."
    return PlanResult(message=message, candidates=candidates)

