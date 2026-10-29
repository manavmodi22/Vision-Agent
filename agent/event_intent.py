"""Bounded checks for explicit event intent; never repairs a model decision."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

Operator = Literal[">=", "<=", ">", "<", "==", "!="]
SMALL = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20), strict=True))
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10), strict=True))
WORDS = "|".join(sorted([*SMALL, *TENS, "hundred", "thousand", "dozen", "half", "quarter"], key=len, reverse=True))
QUANTITY = rf"(?:[-+]?\d{{1,5}}(?:\.\d{{1,3}})?|\.\d{{1,3}}|(?:a\s+)?(?:{WORDS})(?:[- ]+(?:and[- ]+)?(?:{WORDS})){{0,5}})"
UNITS = r"(?:seconds?|secs?|s|minutes?|mins?)"
NEGATIVE = re.compile(
    r"\b(?:no|without|do not|don't|never|disable|stop)\s+"
    r"(?:(?:create|creating|emit|emitting|generate|generating|trigger|triggering|send|sending|save|saving|raise|raising|record|recording|store|storing|persist|persisting)\s+)?"
    r"(?:(?:a|an|any|local|external|outbound|evidence)\s+){0,3}"
    r"(?P<kind>event triggers?|events?|alerts?|notifications?|notify|notifying|flagging|flags?|evidence|crops?|frames?|images?|storage)\b", re.I)
POSITIVE = re.compile(
    r"\b(?:create|emit|generate|record|save|send|raise|trigger|produce)\s+"
    r"(?:(?:a|an|the|one|local|evidence)\s+){0,4}(?:events?|alerts?|notifications?)\b"
    r"|\b(?:save|record)\s+(?:local\s+)?evidence\b"
    r"|\b(?:save|record)\s+(?:(?:a|an|the|local|detected)\s+){0,3}(?:crops?|frames?)(?:\s+evidence)?\b"
    r"|\b(?:alert|notify|flag)\s+(?:me|us|when|if|whenever|on|a|the|any|each|every)\b"
    r"|(?:^|[.;!?]\s*|\band\s+|\bthen\s+|\bplease\s+|\bto\s+)(?:flag|alert|notify)\b"
    r"|\b(?:alerts?|notifications?|events?)\s+(?:when|if|whenever|on)\b"
    r"|\breport\s+(?:when|if)\b", re.I)
COMPARISONS: tuple[tuple[str, Operator], ...] = (
    (r"not equal to|does not equal", "!="),
    (r"at least|no fewer than|not less than", ">="),
    (r"at most|no more than|not more than|up to", "<="),
    (r"more than|greater than|over|above|exceeds?", ">"),
    (r"fewer than|less than|under|below", "<"),
    (r"exactly|equal to|equals?", "=="),
    (r"reaches?|(?:count\s+)?threshold\s*(?:of|is|:|=)?|capacity\s*(?:of|is|:|=)?|full at", ">="),
)


def _under_hundred(tokens: list[str]) -> int:
    if not tokens:
        return 0
    if len(tokens) == 1 and tokens[0] in SMALL | TENS:
        return (SMALL | TENS)[tokens[0]]
    if len(tokens) == 2 and tokens[0] in TENS and tokens[1] in SMALL and 0 < SMALL[tokens[1]] < 10:
        return TENS[tokens[0]] + SMALL[tokens[1]]
    raise ValueError("Use a simple, explicit numeric quantity")


def _under_thousand(tokens: list[str]) -> int:
    if "hundred" not in tokens:
        return _under_hundred(tokens)
    index = tokens.index("hundred")
    prefix = _under_hundred(tokens[:index]) if index else 1
    if not 1 <= prefix <= 9 or tokens.count("hundred") != 1:
        raise ValueError("Use a simple, explicit numeric quantity")
    return prefix * 100 + _under_hundred(tokens[index + 1:])


def number(value: str) -> float:
    cleaned = value.strip().lower()
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", cleaned):
        return float(cleaned)
    tokens = [token for token in re.split(r"[- ]+", cleaned) if token not in {"a", "and"}]
    if len(tokens) == 1 and tokens[0] in {"half", "quarter", "dozen"}:
        return {"half": .5, "quarter": .25, "dozen": 12.0}[tokens[0]]
    if "thousand" in tokens:
        index = tokens.index("thousand")
        prefix = _under_hundred(tokens[:index]) if index else 1
        if not 1 <= prefix <= 10 or tokens.count("thousand") != 1:
            raise ValueError("Use a simple, explicit numeric quantity")
        return float(prefix * 1000 + _under_thousand(tokens[index + 1:]))
    return float(_under_thousand(tokens))


def _count(value: str) -> int:
    result = number(value)
    if not result.is_integer() or not 0 <= result <= 10000:
        raise ValueError("Count thresholds must be whole numbers from zero to 10,000; ask for a supported count")
    return int(result)


def _non_count_context(text: str, start: int, end: int) -> bool:
    return bool(re.search(r"(?:recall|precision|confidence|accuracy|metric|target)\s*(?:of|is|to|=|:)?\s*$", text[max(0, start - 40):start], re.I)
                or re.match(rf"\s*{UNITS}\b", text[end:], re.I))


def comparison(text: str) -> tuple[Operator, int] | None:
    found: list[tuple[int, int, Operator, int]] = []
    for match in re.finditer(rf"\bcount\s*(>=|<=|==|!=|>|<)\s*({QUANTITY})\b", text, re.I):
        found.append((match.start(), match.end(), cast(Operator, match.group(1)), _count(match.group(2))))
    for phrase, operator in COMPARISONS:
        for match in re.finditer(rf"\b(?:{phrase})\s+({QUANTITY})\b", text, re.I):
            if _non_count_context(text, match.start(), match.end()) or any(start <= match.start() < end for start, end, _, _ in found):
                continue
            found.append((match.start(), match.end(), operator, _count(match.group(1))))
    # A quantity attached to an object after "at/with" is a count, not a time or metric.
    for literal in re.finditer(rf"\b(?:at|with)\s*({QUANTITY})\s+([a-z][a-z_-]*)\b", text, re.I):
        unit = literal.group(2).lower()
        if unit in {"am", "pm", "fps", "frames", "images", "percent", "confidence", "recall", "precision", "accuracy"} or re.fullmatch(UNITS, unit, re.I):
            continue
        if not any(start <= literal.start() < end for start, end, _, _ in found):
            found.append((literal.start(), literal.end(), ">=", _count(literal.group(1))))
    if not found and re.search(r"\bfull\b", text, re.I):
        clarification = re.search(rf"User clarification:\s*({QUANTITY})\b", text, re.I)
        if clarification and not _non_count_context(text, clarification.start(), clarification.end()):
            found.append((clarification.start(), clarification.end(), ">=", _count(clarification.group(1))))
        full = re.search(rf"\bfull\s+(?:with|when (?:it|there) (?:has|are))\s+({QUANTITY})\b", text, re.I)
        if full and not _non_count_context(text, full.start(), full.end()):
            found.append((full.start(), full.end(), ">=", _count(full.group(1))))
    unique = {(operator, value) for _, _, operator, value in found}
    if len(unique) > 1:
        raise ValueError("This app supports one count comparison per candidate; ask which conflicting condition to use")
    return next(iter(unique)) if unique else None


def duration(text: str) -> float | None:
    pattern = rf"\b(?:for|after|hold(?:\s+for)?|duration(?:\s+(?:of|is))?|dwell(?:\s+(?:of|is))?)\s+(?:at least\s+)?({QUANTITY})\s*({UNITS})\b"
    values = set()
    for match in re.finditer(pattern, text, re.I):
        seconds = number(match.group(1)) * (60 if match.group(2).lower().startswith("min") else 1)
        if not 0 <= seconds <= 3600:
            raise ValueError("A hold duration must be from zero to 3,600 seconds; ask for a supported duration")
        values.add(seconds)
    if len(values) > 1:
        raise ValueError("This app supports one hold duration per candidate; ask which conflicting duration to use")
    return next(iter(values)) if values else None


@dataclass(frozen=True)
class EventIntent:
    requested: bool = False
    disabled: bool = False
    comparison: tuple[Operator, int] | None = None
    hold_seconds: float | None = None
    unknown_full: bool = False
    ambiguous_negation: bool = False
    excludes_storage: bool = False


def event_intent(brief: str, *, parse_counts: bool = True) -> EventIntent:
    if len(brief) > 12000:
        raise ValueError("The task brief exceeds the bounded intent-check budget")
    text = brief.rsplit("User request:\n", 1)[-1].replace("’", "'")
    negatives = list(NEGATIVE.finditer(text))
    excludes_storage = any(re.fullmatch(r"evidence|crops?|frames?|images?|storage", match.group("kind"), re.I) for match in negatives)
    remaining = NEGATIVE.sub(" ", text)
    requested = bool(POSITIVE.search(remaining))
    only_display = bool(re.search(r"\b(?:show|display)\s+(?:boxes|counts|bounding boxes)\s+only\b|\bcount[- ]only\b", text, re.I))
    global_negative = any(not re.fullmatch(r"alerts?|notifications?|notify|notifying", match.group("kind"), re.I) for match in negatives)
    conditional_negative = any(re.match(r"\s+(?:unless|until|before|below|under)\b", text[match.end():], re.I) for match in negatives)
    conflicting = conditional_negative or (requested and (global_negative or only_display))
    disabled = bool(negatives or only_display) and not requested
    if not requested:
        return EventIntent(disabled=disabled, ambiguous_negation=conflicting, excludes_storage=excludes_storage)
    if not parse_counts:
        return EventIntent(requested=True, disabled=disabled, ambiguous_negation=conflicting,
                           excludes_storage=excludes_storage)
    condition = comparison(text)
    hold = duration(text)
    unknown_full = bool(re.search(r"\bfull\b", text, re.I)) and condition is None
    presence = bool(re.search(r"\b(?:when|whenever|if|once)\b[^.;!?]{0,70}\b(?:appears?|detected|seen|present)\b|\b(?:on|upon)\s+(?:any\s+)?detection\b", text, re.I))
    if condition is None and not unknown_full and (presence or not re.search(r"\b(?:when|if|whenever|capacity|threshold|crowded|high)\b", text, re.I)):
        condition = (">=", 1)
    return EventIntent(requested=True, disabled=disabled, comparison=condition,
                       hold_seconds=hold, unknown_full=unknown_full, ambiguous_negation=conflicting,
                       excludes_storage=excludes_storage)
