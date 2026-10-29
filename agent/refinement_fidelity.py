"""Reject unit or metric changes that contradict explicit user quantities.

These checks validate the model's proposal; they never generate a replacement
patch or execute an edit when interpretation fails.
"""
import math
import re

from agent.preprocessing_fidelity import validate_preprocessing_fidelity
from spec.refinement import RefinementContext, RefinementPatch

_ONES = {word: value for value, word in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"))}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+|(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|hundred|half|quarter)"
_UNIT = r"(?:milliseconds?|ms|seconds?|secs?|s|minutes?|mins?|hours?)"


def _number(value: str) -> float:
    value = value.lower().replace("-", " ")
    try:
        return float(value)
    except ValueError:
        if value in {"a", "an"}:
            return 1
        if value in {"half", "quarter", "hundred"}:
            return {"half": .5, "quarter": .25, "hundred": 100.0}[value]
        return float(sum(_ONES.get(part, _TENS.get(part, 0)) for part in value.split()))


def explicit_sampling_fps(prompt: str) -> float | None:
    matches: list[tuple[int, float]] = []
    interval = re.compile(r"(?<![\w.])(?:(?P<frames>" + _NUMBER + r"|a|an)\s+)?frames?\s+(?:every|per|a|/)\s*(?:(?P<duration>" + _NUMBER + r")\s*)?(?P<unit>" + _UNIT + r")\b", re.I)
    for match in interval.finditer(prompt):
        duration = _number(match.group("duration")) if match.group("duration") else 1
        unit = match.group("unit").lower()
        factor = .001 if unit.startswith("milli") or unit == "ms" else 60 if unit.startswith("min") else 3600 if unit.startswith("hour") else 1
        if duration <= 0:
            raise ValueError("A sampling interval must be positive; ask for a valid duration")
        frames = _number(match.group("frames")) if match.group("frames") else 1
        matches.append((match.start(), frames / (duration * factor)))
    for match in re.finditer(r"(?<![\w.])(" + _NUMBER + r")\s*fps\b", prompt, re.I):
        matches.append((match.start(), _number(match.group(1))))
    return max(matches)[1] if matches else None


def validate_explicit_fidelity(patches: list[RefinementPatch], prompt: str, context: RefinementContext) -> None:
    validate_preprocessing_fidelity(patches, prompt, context)
    literal_prefix = r"\b(?:contains?|equals?|match(?:es)?(?:\s+against)?|expected\s+(?:label|text)\s+(?:is|to)(?:\s+now)?)\s+"
    literals = list(re.finditer(literal_prefix + r"(?:(?P<quote>[\"'])(?P<quoted>.{1,256}?)(?P=quote)|(?P<code>[A-Za-z0-9]+[-_][A-Za-z0-9][A-Za-z0-9_-]*))", prompt, re.I))
    expected = (literals[-1].group("quoted") or literals[-1].group("code")) if literals else None
    unquoted = re.sub(r"(?<!\w)([\"'])(.*?)\1(?!\w)", "", prompt)
    modes = list(re.finditer(r"(?<![\w-])(?:contains?|exact(?:ly)?)(?![\w-])", unquoted, re.I))
    mode = ("contains" if modes[-1].group().lower().startswith("contain") else "exact") if modes else None
    text_patches = [patch for patch in patches if patch.kind == "expected_text"]
    for patch in text_patches:
        if expected is not None and patch.expected_text != expected:
            raise ValueError(f"The user explicitly supplied literal {expected!r}; preserve it exactly")
        indices = range(len(context.candidates)) if patch.target_scope() == "all" else [context.selected_candidate_index]
        for index in indices:
            current = [block for block in context.candidates[index].blocks if block.type == "match" and (not patch.block_id or block.id == patch.block_id)]
            effective_mode = patch.match_mode or (current[0].params.get("mode", "contains") if len(current) == 1 else "exact")
            if mode is not None and effective_mode != mode:
                raise ValueError(f"The user explicitly requested a {mode} text comparison; preserve that operator")
    requested_fps = explicit_sampling_fps(prompt)
    if requested_fps is not None:
        fps_patches = [patch for patch in patches if patch.kind == "sample_fps"]
        if not fps_patches or any(patch.fps is None or not math.isclose(patch.fps, requested_fps, rel_tol=1e-9, abs_tol=1e-9)
                                  for patch in fps_patches):
            raise ValueError(f"The explicit sampling rate converts to {requested_fps:g} frames per second; preserve its units and value")
    metrics = list(re.finditer(r"\b(count[_ -]?mae|mean absolute count error|precision|recall|text[_ -]?accuracy)\b", prompt, re.I))
    metrics = [match for match in metrics if not re.search(r"\b(?:not|rather than|instead of|from)\s*$", prompt[max(0, match.start() - 15):match.start()], re.I)]
    if not metrics:
        return
    # The most recent explicit metric wins in a contextual answer.
    match = metrics[-1]
    name = match.group(1).lower().replace("-", "_").replace(" ", "_")
    metric = "count_mae" if name in {"countmae", "mean_absolute_count_error"} else "text_accuracy" if name == "textaccuracy" else name
    suffix = prompt[match.end():match.end() + 160]
    target_match = re.search(r"(?:^\s*|\btarget\b|\brequire\b|\bat least\b|\bat most\b|\bmaximum\b|\bminimum\b|>=|<=|=|:)\s*(?:of\s+|at least\s+|at most\s+)?(" + _NUMBER + r")\s*(%|percent)?", suffix, re.I)
    target = _number(target_match.group(1)) if target_match else None
    if target_match and target_match.group(2) and target is not None:
        target /= 100
    selected_only = bool(re.search(r"\b(selected|this candidate|current candidate)\b", prompt, re.I))
    indices = [context.selected_candidate_index] if selected_only else range(len(context.candidates))
    for index in indices:
        actual_metric, actual_target = context.candidates[index].eval.metric, context.candidates[index].eval.target
        for patch in patches:
            if patch.kind == "eval_target" and (patch.target_scope() == "all" or index == context.selected_candidate_index):
                actual_metric = patch.eval_metric or actual_metric
                actual_target = patch.eval_target if patch.eval_target is not None else actual_target
        if actual_metric != metric or (target is not None and not math.isclose(actual_target, target, rel_tol=1e-9, abs_tol=1e-9)):
            raise ValueError(f"The user explicitly requested metric {metric}" + (f" with target {target:g}" if target is not None else "") + "; preserve the effective metric and target")
