"""Product-language descriptions derived only from the connected pipeline graph."""
from __future__ import annotations

import json
import math
import re

from pydantic import JsonValue

from spec.models import BlockSpec, PipelineSpec

_COMPARISONS = {">=": "at least", "<=": "at most", ">": "more than", "<": "less than",
                "==": "exactly", "!=": "different from"}
_RULE = re.compile(r"^\s*count\s*(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+)?)\s*$")


def _quoted(value: str) -> str:
    display = value if len(value) <= 256 else value[:253] + "…"
    return json.dumps(display, ensure_ascii=False)


def _names(values: list[str], noun: str) -> str:
    displayed = [_quoted(value) for value in values[:4]]
    if len(values) > 4:
        displayed.append(f"{len(values) - 4} other {noun}")
    if len(displayed) <= 1:
        return displayed[0] if displayed else "objects"
    return ", ".join(displayed[:-1]) + " and " + displayed[-1]


def _strings(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _source(block: BlockSpec, port: str, blocks: dict[str, BlockSpec]) -> BlockSpec | None:
    reference = block.inputs.get(port, "")
    return blocks.get(reference[1:].split(".", 1)[0]) if reference.startswith("$") else None


def _event_sources(blocks: dict[str, BlockSpec]) -> set[str]:
    """Only sink-connected behavior is visible in runtime event outputs."""
    result: set[str] = set()
    for sink in blocks.values():
        if sink.type != "sink_event":
            continue
        current, visited = _source(sink, "event", blocks), set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            if current.type != "sink_event":
                result.add(current.id)
                break
            current = _source(current, "event", blocks)
    return result


def _count_scope(count: BlockSpec, blocks: dict[str, BlockSpec]) -> tuple[list[str], str, str | None]:
    current = _source(count, "dets", blocks)
    classes: list[str] = []
    region: BlockSpec | None = None
    detector_id: str | None = None
    visited: set[str] = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.type == "zone_filter":
            if region is None:
                region = current
            current = _source(current, "dets", blocks)
        elif current.type in {"detect", "detect_open_vocab"}:
            classes, detector_id = _strings(current.params.get("classes")), current.id
            break
        else:
            break
    scope = "in each processed frame"
    if region is not None:
        ids = _strings(region.params.get("include_ids"))
        zones = region.params.get("zones")
        if not ids and isinstance(zones, list):
            ids = [value for zone in zones if isinstance(zone, dict) and isinstance(value := zone.get("id"), str)]
        if len(ids) == 1:
            scope = "in region " + _names(ids, "regions")
        elif ids:
            scope = "in each of regions " + _names(ids, "regions")
        else:
            scope = "in each saved region"
        if count.params.get("include_unassigned") is True:
            scope += ", with a separate count outside those regions"
    return classes, scope, detector_id


def _rule_sentence(rule: BlockSpec) -> str | None:
    expression, hold = rule.params.get("when", "count >= 1"), rule.params.get("hold_s", 0)
    match = _RULE.fullmatch(expression) if isinstance(expression, str) else None
    if not match or isinstance(hold, bool) or not isinstance(hold, int | float) or not math.isfinite(hold) or hold < 0:
        return None
    condition = _COMPARISONS[match.group(1)] + " " + f"{float(match.group(2)):g}"
    if hold:
        return f"Creates a local event when that count stays {condition} for {hold:g} seconds."
    return f"Creates a local event when that count is {condition}."


def _bounded(sentences: list[str]) -> str:
    result: list[str] = []
    for sentence in dict.fromkeys(sentences):
        if sum(map(len, result)) + len(sentence) + len(result) > 1540:
            result.append("Further configured behavior is shown in the workflow.")
            break
        result.append(sentence)
    return " ".join(result) or "Processes sampled frames."


def describe_pipeline(spec: PipelineSpec) -> str:
    """Describe configured behavior, without claiming preview success or approval."""
    blocks = {block.id: block for block in spec.blocks}
    emitted = _event_sources(blocks)
    sentences: list[str] = []
    counted_detectors: set[str] = set()
    for count in spec.blocks:
        if count.type != "count_per_zone":
            continue
        classes, scope, detector_id = _count_scope(count, blocks)
        if detector_id:
            counted_detectors.add(detector_id)
        count_phrase = "the combined count" if len(classes) > 1 else "counts"
        sentences.append(f"Displays {count_phrase} of {_names(classes, 'classes')} {scope}.")
        for rule in spec.blocks:
            if rule.id in emitted and rule.type == "rule" and _source(rule, "value", blocks) is count:
                sentence = _rule_sentence(rule)
                if sentence:
                    sentences.append(sentence)
    for reader in spec.blocks:
        if reader.type not in {"ocr", "barcode"}:
            continue
        subject = "printed text" if reader.type == "ocr" else "barcodes"
        sentences.append(f"Reads {subject}.")
        for comparison in spec.blocks:
            if comparison.type != "match" or _source(comparison, "text", blocks) is not reader:
                continue
            expected, mode = comparison.params.get("expected"), comparison.params.get("mode", "contains")
            if isinstance(expected, str) and mode in {"contains", "exact"}:
                check = "contains" if mode == "contains" else "exactly matches"
                sentences.append(f"Checks whether the read text {check} {_quoted(expected)}.")
                if comparison.id not in emitted:
                    continue
                emit = comparison.params.get("emit", "all")
                if emit == "matched":
                    sentences.append("Creates a local event only when that comparison matches.")
                elif emit == "mismatched":
                    sentences.append("Creates a local event only when that comparison does not match.")
    for detector in spec.blocks:
        if detector.type in {"detect", "detect_open_vocab"} and detector.id not in counted_detectors:
            sentences.append(f"Detects {_names(_strings(detector.params.get('classes')), 'classes')}.")
    return _bounded(sentences)


def describe_candidates(candidates: list[PipelineSpec]) -> str:
    descriptions = [describe_pipeline(candidate) for candidate in candidates]
    if len(descriptions) == 1:
        return descriptions[0]
    if descriptions and len(set(descriptions)) == 1:
        return f"Configured {len(descriptions)} alternatives. " + descriptions[0]
    return "\n".join(f"Candidate {index + 1}: {description}" for index, description in enumerate(descriptions))
