"""Semantic checks that keep a local model's proposal faithful to explicit inputs."""

import re

from agent.contracts import PlanDecision
from agent.event_intent import event_intent


def validate_event_values(decision: PlanDecision, brief: str) -> None:
    """Reject intent/value drift; explicit user values are never generated repairs."""
    if not decision.choices:
        return
    intent = event_intent(brief, parse_counts=any(choice.pipeline_type == "detection" and choice.use_case != "labels" for choice in decision.choices))
    if intent.excludes_storage:
        raise ValueError("Approved runs retain local detection crops and frame evidence; disabling evidence storage is unsupported. Ask whether preview-only use or the existing retention behavior is acceptable, rather than returning a candidate that promises no storage.")
    if intent.ambiguous_negation:
        raise ValueError("The event instructions have conflicting or conditional negation; ask for one explicit event condition")
    for choice in decision.choices:
        if choice.pipeline_type != "detection" or choice.use_case == "labels":
            continue
        if not intent.requested or intent.disabled:
            if choice.count_threshold is not None or choice.hold_seconds != 0:
                raise ValueError("This task requests output without an event trigger. Set count_threshold null and hold_seconds zero; do not invent event behavior.")
            continue
        if intent.unknown_full:
            continue  # The prerequisite asks for capacity, regardless of a model guess.
        if intent.comparison is None:
            raise ValueError("The requested event has no clear count condition; ask what count should trigger it instead of inventing a threshold")
        operator, threshold = intent.comparison
        if choice.count_threshold != threshold or choice.count_operator != operator:
            raise ValueError(f"The user requested an event with count {operator} {threshold}; set count_threshold {threshold} and count_operator {operator!r} exactly. Do not omit the event or ask for an already-supplied count.")
        hold = intent.hold_seconds if intent.hold_seconds is not None else 0
        if choice.hold_seconds != hold:
            raise ValueError(f"The requested hold duration is {hold:g} seconds; preserve it exactly in hold_seconds, without inventing or dropping a delay.")


def validate_output_behavior(decision: PlanDecision, brief: str) -> None:
    validate_event_values(decision, brief)
    latest = brief.rsplit("User request:\n", 1)[-1]
    counting = re.search(r"\bcount(?:ing)?\b", latest, re.IGNORECASE)
    explicit_metric = re.search(r"\b(?:count_mae|precision|recall|text_accuracy)\b", latest, re.IGNORECASE)
    for choice in decision.choices:
        if choice.pipeline_type == "detection" and counting and not explicit_metric and choice.metric != "count_mae":
            raise ValueError("This is a counting task; use count_mae target 0.5 unless the user specifies another evaluation metric or target.")


def validate_spatial_intent(decision: PlanDecision, brief: str) -> None:
    latest = brief.rsplit("User request:\n", 1)[-1]
    spatial = re.search(r"\b(?:per[- ]lane|each (?:lane|zone|region)|inside (?:the )?(?:lane|zone|region)|saved (?:lane|zone|region)|marked (?:lane|zone|region)|lanes? [A-Z](?:\b|[-–]))", latest, re.IGNORECASE)
    whole_image = re.search(r"\b(?:across each image|whole[- ]image|entire (?:image|frame)|ignore (?:the )?(?:zones|regions|lanes))\b", latest, re.IGNORECASE)
    region_reference = re.search(r"\b(?:lanes?|zones?|regions?|areas?|boundary|boundaries|polygons?)\b", latest, re.IGNORECASE)
    if not region_reference:
        for choice in decision.choices:
            if choice.use_case == "custom" and (choice.use_zones or choice.zone_ids):
                raise ValueError("The user did not request any spatial region. Set use_zones false and zone_ids []; saved geometry alone does not authorize filtering the image.")
    if whole_image and not spatial:
        for choice in decision.choices:
            if choice.use_zones or choice.zone_ids or choice.use_case == "pallets":
                raise ValueError("The user requested whole-image counts. Use the custom pattern with use_zones false and zone_ids []; saved geometry is not a request to filter by it.")
    if spatial:
        for choice in decision.choices:
            if choice.pipeline_type == "detection" and not (choice.use_zones or choice.zone_ids or choice.use_case == "pallets"):
                raise ValueError("The user requested spatial counts; use_zones must be true. Select named saved regions or request actual boundaries, never silently count the whole image.")


def validate_explicit_metric(decision: PlanDecision, brief: str) -> None:
    requested = list(re.finditer(
        r"\b(count_mae|precision|recall|text_accuracy)\s*(?:target|of|=|>=|<=|:)?\s*(\d+(?:\.\d+)?)(%)?",
        brief, re.IGNORECASE,
    ))
    if not requested:
        return
    match = requested[-1]
    metric, target = match.group(1).lower(), float(match.group(2))
    if match.group(3):
        target /= 100
    for choice in decision.choices:
        if choice.metric != metric or abs(choice.target - target) > 1e-9:
            raise ValueError(f"The user explicitly requested {metric} target {target}; preserve that metric and target exactly.")


_PLACEHOLDERS = frozenset({"a", "an", "the", "expected", "correct", "right", "proper", "default",
    "sku", "code", "value", "text", "label", "barcode", "package", "it", "them", "that", "whether",
    "for", "against", "exactly", "unknown", "missing", "unspecified", "tbd", "none", "null"})
_READING_COMPARISON = r"\b(?:check|verify|(?:mis)?match(?:es|ing)?|compare|comparison|expected|contains?|equals?)\b"


def explicit_expected_text(brief: str) -> str | None:
    """Recognize an explicit literal/code after a text comparison verb only."""
    latest = brief.rsplit("User request:\n", 1)[-1]
    prefix = r"\b(?:check\s+(?:for|against)|contains?|equals?|compare(?:\s+(?:it|them))?\s+(?:with|against)|(?:mis)?match(?:es)?(?:\s+against)?|(?:expected|correct)\s+(?:SKU|code|value|text)\s*(?:is|=|:))\s+"
    quoted = re.search(prefix + r"[\"']([^\"']{1,256})[\"']", latest, re.IGNORECASE)
    if quoted:
        return quoted.group(1)
    codes = re.finditer(prefix + r"([A-Za-z0-9][A-Za-z0-9_-]{0,255})\b", latest, re.IGNORECASE)
    for code in codes:
        suffix = latest[code.end():]
        complete = bool(re.match(r"(?:\s*$|[.!?;,](?:\s|$)|\s+exactly\s*(?:[.!?]|$))", suffix, re.I))
        if complete and code.group(1).lower() not in _PLACEHOLDERS:
            return code.group(1)
    if "User clarification:" in latest:
        answer = latest.rsplit("User clarification:", 1)[-1].strip()
        quoted_answer = re.fullmatch(r"[\"']([^\"']{1,256})[\"'][.]?", answer)
        if quoted_answer:
            return quoted_answer.group(1)
        simple_answer = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_-]{0,255})[.]?", answer)
        if simple_answer and simple_answer.group(1).lower() not in _PLACEHOLDERS:
            return simple_answer.group(1)
    return None


def unresolved_expected_text(brief: str) -> bool:
    latest = brief.rsplit("User request:\n", 1)[-1]
    return explicit_expected_text(brief) is None and bool(re.search(_READING_COMPARISON, latest, re.I))


def validate_reading_literal(decision: PlanDecision, brief: str) -> None:
    expected = explicit_expected_text(brief)
    latest = brief.rsplit("User request:\n", 1)[-1].replace("’", "'")
    read_only = (not re.search(_READING_COMPARISON, latest, re.I)
                 or bool(re.search(r"\b(?:no|without)\s+(?:expected|comparison|matching)|\b(?:do not|don't)\s+(?:compare|match|check)", latest, re.I)))
    for choice in decision.choices:
        if choice.pipeline_type not in {"ocr", "barcode"} and choice.use_case != "labels":
            continue
        if read_only:
            if choice.expected_text is not None:
                raise ValueError("This is a read-only task without a comparison; expected_text must be null. Do not invent a comparison value or add a match block.")
            continue
        if expected is not None and choice.expected_text != expected:
            raise ValueError(f"The user explicitly supplied expected text {expected!r}; preserve it exactly instead of omitting it or asking for it again.")
        if (expected is None and choice.expected_text is not None
                and re.search(_READING_COMPARISON, latest, re.I)
                and not re.search(r"(?<!\w)" + re.escape(choice.expected_text) + r"(?!\w)", latest)):
            raise ValueError("The proposed expected text is absent from the brief and clarification; ask for the comparison value instead of inventing a literal.")


def validate_reading_mode(decision: PlanDecision, brief: str) -> None:
    """Preserve explicit equality/substring semantics, without rewriting a choice."""
    readers = [choice for choice in decision.choices
               if choice.pipeline_type in {"ocr", "barcode"} or choice.use_case == "labels"]
    if not readers:
        return
    latest = brief.rsplit("User request:\n", 1)[-1]
    # Mode words inside a quoted literal or identifier are comparison data.
    unquoted = re.sub(r"([\"']).{0,500}?\1", " ", latest)
    unquoted = re.sub(r"\b[A-Za-z0-9]+[-_][A-Za-z0-9_-]+\b", " ", unquoted)
    contains = bool(re.search(r"\b(?:contains?|substring|partial\s+match(?:ing)?)\b", unquoted, re.I))
    exact = bool(re.search(r"\b(?:equals?|exact(?:ly)?\s+(?:match(?:es|ing)?|equal(?:s|ity)?)|matches?\s+exactly)\b|\bmatch(?:es)?\b[^.;!?]{0,80}\bexactly\b|\b(?:mode|comparison)\s*(?:is|=|:)?\s*exact\b", unquoted, re.I))
    if contains and exact:
        raise ValueError("The reading request gives conflicting exact and contains comparisons; ask which matching mode to use")
    mode = "exact" if exact else "contains" if contains else None
    if mode is not None and any(choice.match_mode != mode for choice in readers):
        raise ValueError(f"The user explicitly requested match_mode {mode!r}; preserve it exactly instead of changing equality or substring semantics")
    emit = "all"
    if event_intent(brief, parse_counts=False).requested:
        condition = re.search(r"\b(?:when|whenever|if|on)\b(.{1,300})", unquoted, re.I)
        if condition:
            text = condition.group(1).replace("’", "'")
            if re.search(r"\b(?:mismatches?|non[- ]matching|fails?\s+to\s+match|(?:does\s+not|doesn't|not)\s+(?:exactly\s+)?(?:match|contain|equal))\b", text, re.I):
                emit = "mismatched"
            elif re.search(r"\b(?:matches?|contains?|equals?|exact(?:ly)?\s+match)\b", text, re.I):
                emit = "matched"
            else:
                raise ValueError("The reading event condition is unsupported; ask whether to record matching, mismatching, or all comparison results")
    if any(choice.match_emit != emit for choice in readers):
        raise ValueError(f"This reading request requires match_emit {emit!r}; preserve whether local events record matching, mismatching, or all comparison results")


def validate_custom_inputs(decision: PlanDecision, brief: str, classes: list[str]) -> None:
    validate_reading_mode(decision, brief)
    validate_reading_literal(decision, brief)
    confidences = list(re.finditer(r"\bconfidence\s*(?:threshold\s*)?(\d+(?:\.\d+)?)(%)?", brief, re.IGNORECASE))
    for choice in decision.choices:
        if choice.use_case != "custom" or choice.pipeline_type != "detection":
            continue
        if classes and not set(choice.objects) <= set(classes):
            raise ValueError(f"Use the saved ontology names exactly: {', '.join(classes)}.")
        if confidences:
            match = confidences[-1]
            expected = float(match.group(1)) / (100 if match.group(2) else 1)
            if abs(choice.min_confidence - expected) > 1e-9:
                raise ValueError(f"The user requested confidence {expected}; preserve it exactly.")
