"""Reject known delivery setup requests, without interpreting visual app edits.

This capability preflight is deterministic, explicitly recorded, and never emits
patches. The same check is repeated at the MCP mutation boundary.
"""

import re

_CHANNEL = re.compile(r"\b(?:e-?mails?|webhooks?|mqtt)\b", re.I)
_ACTION = re.compile(r"\b(?:send|post|publish|push|forward|route|deliver|notify|configure|enable|connect|set\s+up)\b", re.I)
_NEGATION = re.compile(r"\b(?:don't|do\s+not|never|without|no|skip|omit|forget|stop|disable)\b", re.I)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27')
_CLAUSE = re.compile(r"[;!\n]|[,.?](?!\d)|\b(?:but|and)\b", re.I)
CAPABILITY_QUESTION = (
    "Delivery setup is separate from editing this vision app. Email delivery is not supported here; "
    "configure and approve a webhook or MQTT destination in Alerts. "
    "Should I apply only the vision changes and skip delivery setup?"
)


def delivery_question(prompt: str, previous_question: str = "") -> str | None:
    """Find explicit delivery actions; later clarification can withdraw them.

    Channel mentions in object names and quoted reading literals are not actions.
    This deliberately covers known delivery vocabulary, not arbitrary capabilities.
    """
    pending: set[str] = set()
    turns = re.split(r"\nUser clarification:\s*", prompt, flags=re.I)
    for turn in turns:
        masked = _QUOTED.sub(lambda match: " " * len(match.group()), turn)
        boundaries = list(_CLAUSE.finditer(masked))
        starts = [0] + [item.end() for item in boundaries]
        ends = [item.start() for item in boundaries] + [len(turn)]
        for start, end in zip(starts, ends, strict=True):
            clause, visible = turn[start:end], masked[start:end]
            channels = list(_CHANNEL.finditer(clause))
            actions = list(_ACTION.finditer(visible))
            for channel in channels:
                name = channel.group().lower().replace("-", "").rstrip("s")
                prefix, suffix = visible[:channel.start()], clause[channel.end():]
                # A visual class such as email icon or MQTT sensor is not a destination.
                if re.match(r"\s+(?:icons?|symbols?|sensors?|labels?|logos?|buttons?|objects?|classes?)\b", suffix, re.I) or re.search(
                    r"\bas\s+(?:an?\s+)?(?:object\s+)?class\b", suffix, re.I
                ):
                    continue
                negated = bool(_NEGATION.search(prefix))
                if negated and visible[channel.start():channel.end()].strip():
                    pending.discard(name)
                    continue
                action = any(item.start() < channel.start() for item in actions)
                email_verb = name == "email" and bool(visible[channel.start():channel.end()].strip()) and bool(re.match(r"\s+(?:me|us|the\s+team|someone)\b", suffix, re.I))
                setup = bool(visible[channel.start():channel.end()].strip()) and bool(re.search(r"\b(?:add|use)\s+(?:an?\s+)?$", prefix, re.I))
                if (action or setup or email_verb) and not negated:
                    pending.add(name)
            if re.search(r"\b(?:skip|omit|without|no)\s+(?:any\s+)?(?:delivery|outbound|external)(?:\s+(?:setup|alerts?|notifications?))?\b", visible, re.I):
                pending.clear()
    if (len(turns) > 1 and previous_question == CAPABILITY_QUESTION
            and re.fullmatch(r"\s*yes(?:,?\s+please)?[.!]?\s*", turns[-1], re.I)):
        pending.clear()  # Answer to our specific vision-only question, not blanket consent.
    return CAPABILITY_QUESTION if pending else None
