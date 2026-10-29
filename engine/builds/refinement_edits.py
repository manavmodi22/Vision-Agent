"""Pure, typed graph edits. New behavior needs an unambiguous supported input."""
from decimal import Decimal

from engine.blocks.logic import parse_rule
from engine.blocks.params import MatchParams, RuleParams
from engine.compiler import parse_reference
from spec.models import BlockSpec, EvalConfig, PipelineSpec
from spec.refinement import RefinementPatch


def unique_block(candidate: PipelineSpec, kinds: set[str], identifier: str | None) -> BlockSpec:
    found = [block for block in candidate.blocks
             if block.type in kinds and (identifier is None or block.id == identifier)]
    if len(found) != 1:
        raise ValueError(f"Choose one existing {'/'.join(sorted(kinds))} block; the requested input is missing or ambiguous")
    return found[0]


def detector_classes(candidate: PipelineSpec) -> set[str]:
    return {name for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"}
            for name in class_list(block)}


def class_list(block: BlockSpec) -> list[str]:
    value = block.params.get("classes", ["pallet"])
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ValueError("Existing detector has an invalid class list")
    return [str(name) for name in value]


def new_id(candidate: PipelineSpec, prefix: str) -> str:
    identifiers = {block.id for block in candidate.blocks}
    name, suffix = prefix, 1
    while name in identifiers:
        name, suffix = f"{prefix}_{suffix}", suffix + 1
    return name


def ensure_sink(candidate: PipelineSpec, block: BlockSpec) -> None:
    if not any(row.type == "sink_event" and row.inputs.get("event") == f"${block.id}.event"
               for row in candidate.blocks):
        candidate.blocks.append(BlockSpec.model_validate({"id": new_id(candidate, "refined_events"),
            "type": "sink_event", "in": {"event": f"${block.id}.event"}}))


def behavior_block(candidate: PipelineSpec, patch: RefinementPatch) -> BlockSpec:
    kind = "rule" if patch.kind == "count_rule" else "match"
    if any(block.type == kind for block in candidate.blocks) or patch.block_id:
        return unique_block(candidate, {kind}, patch.block_id)
    if kind == "rule":
        if patch.count_threshold is None:
            raise ValueError("Adding a count rule requires an explicit threshold")
        upstream = unique_block(candidate, {"count_per_zone"}, None)
        result = BlockSpec.model_validate({"id": new_id(candidate, "refined_rule"), "type": "rule",
            "params": {"when": "count >= 1", "hold_s": 0}, "in": {"value": f"${upstream.id}.counts"}})
    else:
        upstream = unique_block(candidate, {"ocr", "barcode"}, None)
        result = BlockSpec.model_validate({"id": new_id(candidate, "refined_match"), "type": "match",
            "params": {"expected": patch.expected_text, "mode": "exact"}, "in": {"text": f"${upstream.id}.text"}})
    candidate.blocks.append(result)
    ensure_sink(candidate, result)
    return result


def apply_edit(candidate: PipelineSpec, patch: RefinementPatch, names: dict[str, str]) -> None:
    if patch.kind == "eval_target":
        metric = patch.eval_metric or candidate.eval.metric
        types = {block.type for block in candidate.blocks}
        required = {"ocr", "barcode", "vlm_judge"} if metric == "text_accuracy" else {"detect", "detect_open_vocab"}
        if not types.intersection(required):
            raise ValueError("The requested evaluation metric has no matching output in this app")
        candidate.eval = EvalConfig(set=candidate.eval.set, metric=metric,
            target=patch.eval_target if patch.eval_target is not None else candidate.eval.target)
    elif patch.kind == "sample_fps":
        unique_block(candidate, {"frame_sample"}, patch.block_id).params["fps"] = patch.fps
    elif patch.kind == "count_rule":
        block = behavior_block(candidate, patch)
        original = RuleParams.model_validate(block.params)
        rule = parse_rule(original.when)
        threshold = patch.count_threshold if patch.count_threshold is not None else rule.threshold
        operation = patch.count_operator or rule.operation
        if threshold != rule.threshold or operation != rule.operation:
            block.params["when"] = f"count {operation} {Decimal(str(threshold)):f}"
        if patch.hold_s is not None:
            block.params["hold_s"] = patch.hold_s
        ensure_sink(candidate, block)
    elif patch.kind == "expected_text":
        block = behavior_block(candidate, patch)
        original_match = MatchParams.model_validate(block.params)
        owner, _ = parse_reference(block.inputs["text"])
        unique_block(candidate, {"ocr", "barcode"}, owner)
        block.params.update(expected=patch.expected_text, mode=patch.match_mode or original_match.mode)
        ensure_sink(candidate, block)
    else:
        detector = unique_block(candidate, {"detect", "detect_open_vocab"}, patch.block_id)
        if patch.kind == "confidence":
            detector.params["min_conf"] = patch.confidence
            return
        current = class_list(detector)
        requested = [names.get(name.casefold(), name) for name in patch.classes]
        if patch.kind == "replace_classes":
            current = requested
        elif patch.kind == "remove_classes":
            current = [name for name in current if name.casefold() not in {value.casefold() for value in requested}]
        else:
            current += [name for name in requested if name.casefold() not in {value.casefold() for value in current}]
        detector.params["classes"] = list(current)
