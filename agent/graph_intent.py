"""Reject explicit goal drift in a composed proposal without rewriting its nodes."""
import re

from pydantic import JsonValue

from agent.contracts import PlanDecision
from agent.event_intent import event_intent
from agent.graph_authoring import model_choice
from agent.graph_language import branch_request, clauses_for_branch
from agent.graph_reading import comparison_requested, event_request_text, validate_reader_branch
from agent.graph_structure import ordered_nodes
from agent.graph_transforms import validate_transforms
from agent.task_validation import (
    reading_instruction_text,
    validate_custom_inputs,
    validate_explicit_metric,
    validate_output_behavior,
    validate_spatial_intent,
)
from spec.authoring import (
    BarcodeNode,
    CountNode,
    DetectNode,
    EventNode,
    GraphCandidate,
    MatchNode,
    OCRNode,
    RuleNode,
    ZoneNode,
)


def _requested(request: str, pattern: str) -> bool:
    visible = reading_instruction_text(request)
    return any(not re.search(r"\b(?:do not|don't|never|without|no)\b[^.;!?,]{0,60}$",
                             visible[max(0, match.start() - 80):match.start()], re.I)
               for match in re.finditer(pattern, visible, re.I))


def validate_graph_intent(graphs: list[GraphCandidate], brief: str, context: dict[str, JsonValue]) -> None:
    request = brief.rsplit("User request:\n", 1)[-1]
    if _requested(request, r"\b(?:segment(?:ation)?|pixel[- ]masks?|track(?:ing)?|trajector(?:y|ies)|line[- ]crossing|tiling|VLM|visual judge)\b"):
        raise ValueError("This requested operation is not supported by the current graph authoring vocabulary; explain the missing capability instead of omitting it")
    instructions = reading_instruction_text(event_request_text(brief))
    intent = event_intent(instructions, parse_counts=False)
    raw_classes = context.get("classes", [])
    classes = [value for value in raw_classes if isinstance(value, str)] if isinstance(raw_classes, list) else []
    for graph in graphs:
        ordered_nodes(graph)
        sinks = [node for node in graph.nodes if isinstance(node, EventNode)]
        if intent.excludes_storage:
            raise ValueError("Approved runs retain local evidence; ask whether preview-only use or normal retention is acceptable")
        if intent.ambiguous_negation:
            raise ValueError("The event request has conflicting or conditional negation; ask for a clear condition")
        if sinks and (intent.disabled or not intent.requested):
            raise ValueError("No local events were requested. Keep visible comparisons, but remove every sink_event node")
        if intent.requested and not intent.disabled and not sinks:
            raise ValueError("The user requested local events; include the requested event behavior or ask which condition applies")
        validate_transforms(graph, request)
        nodes = {node.id: node for node in graph.nodes}
        zone = next((node for node in graph.nodes if isinstance(node, ZoneNode)), None)
        count = next((node for node in graph.nodes if isinstance(node, CountNode)), None)
        rule = next((node for node in graph.nodes if isinstance(node, RuleNode)), None)
        matches = [node for node in graph.nodes if isinstance(node, MatchNode)]
        readers = [node for node in graph.nodes if isinstance(node, (OCRNode, BarcodeNode))]
        detectors = [node for node in graph.nodes if isinstance(node, DetectNode)]
        if not detectors and _requested(request, r"\b(?:detect|count)\b"):
            raise ValueError("The request includes detection/counting; do not omit the detector branch")
        if _requested(request, r"\b(?:OCR|printed text|printed labels?|read (?:the )?text)\b") and not any(isinstance(node, OCRNode) for node in readers):
            raise ValueError("The request asks for printed text recognition; do not omit its OCR branch")
        if _requested(request, r"\b(?:barcodes?|QR codes?)\b") and not any(isinstance(node, BarcodeNode) for node in readers):
            raise ValueError("The request asks for barcode reading; do not substitute an OCR-only branch")
        if detectors and _requested(request, r"\bcount(?:ing)?\b") and count is None:
            raise ValueError("A counting request needs a count_per_zone output")
        if count is not None and count.include_unassigned and not re.search(r"\b(outside|unassigned)\b", request, re.I):
            raise ValueError("Do not add outside-region counts unless requested")
        if any(sum(match.text == f"${reader.id}.text" for match in matches) > 1 for reader in readers):
            raise ValueError("Use one explicit comparison per reader branch; multiple tests on one reader need a clearer evaluation contract")
        for index, reader in enumerate(readers):
            comparisons = {clause for clause in clauses_for_branch(request, reader.type) if comparison_requested(clause)}
            for other in readers[index + 1:]:
                if comparisons.intersection(clauses_for_branch(request, other.type)):
                    raise ValueError("Multiple reader branches share an unspecified comparison; identify which reader's value should be compared")
        for node in [*detectors, *readers]:
            choice = model_choice(node, graph)
            if isinstance(node, DetectNode):
                choice.use_zones, choice.zone_ids = zone is not None, zone.zone_ids if zone else []
                choice.count_threshold = rule.threshold if rule else None
                choice.count_operator = rule.operator if rule else ">="
                choice.hold_seconds = rule.hold_seconds if rule else 0
                choice.record_events = rule is not None
            else:
                comparison = next((match for match in matches if match.text == f"${node.id}.text"), None)
                choice.expected_text = comparison.expected if comparison else None
                choice.match_mode = comparison.mode if comparison else "contains"
                choice.match_emit = comparison.emit if comparison else "all"
                choice.record_events = comparison is not None and any(sink.event == f"${comparison.id}.event" for sink in sinks)
            decision = PlanDecision(message="Validate the actual composed branch", choices=[choice])
            if isinstance(node, DetectNode):
                # A local event on a separate reader branch is not a detection count rule.
                if not readers or rule is not None:
                    count_intent = event_intent(instructions)
                    if count_intent.requested and not count_intent.disabled and (count_intent.unknown_full or count_intent.comparison is None):
                        raise ValueError("A count event needs a confirmed threshold; ask what count makes the region full")
                    validate_output_behavior(decision, instructions)
                validate_spatial_intent(decision, brief)
                validate_custom_inputs(decision, brief, classes)
            else:
                validate_reader_branch(choice, branch_request(request, node.type))
        primary = detectors[0] if graph.metric != "text_accuracy" and detectors else readers[0] if readers else detectors[0]
        primary_choice = model_choice(primary, graph)
        primary_choice.metric, primary_choice.target = graph.metric, graph.target
        validate_explicit_metric(PlanDecision(message="Validate the evaluation target", choices=[primary_choice]), brief)
        for match in matches:
            if not isinstance(nodes[match.text[1:].split('.')[0]], (OCRNode, BarcodeNode)):
                raise ValueError("Text comparisons must refer to an actual reader branch")
