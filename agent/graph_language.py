"""Conservative task-clause boundaries shared by graph intent guards."""
import re

_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27')
_ROLES = {
    "ocr": re.compile(r"\b(?:OCR|printed[- ](?:text|labels?)|text\s+(?:recognition|reader))\b|\b(?:read|recognize|extract)\s+(?:the\s+)?(?:printed\s+)?(?:text|labels?)\b", re.I),
    "barcode": re.compile(r"\b(?:barcodes?|QR(?:[- ]codes?)?)\b", re.I),
    "detect": re.compile(r"\b(?:detect(?:or|ion|ing)?|count(?:ing)?)\b(?!\s+(?:the\s+)?(?:barcodes?|QR|text))", re.I),
}
_SCOPE = re.compile(r"\b(?:crop|cropping|half|resize|resizing|rescale|scale|resolution|dimensions|compare|comparison|match|contains?|exact(?:ly)?|expected|(?:full|whole|entire)[- ](?:frame|image)|(?:original|native)\s+size|uncropped)\b|\b(?:width|height)\s*\d|\d+\s*(?:x|×|by)\s*\d+", re.I)
_ACTION = re.compile(r"\b(?:read|decode|detect|count|recognize|extract)\b", re.I)


def visible(text: str) -> str:
    """Mask comparison data without moving clause boundaries."""
    return _QUOTED.sub(lambda match: " " * len(match.group()), text)


def roles(text: str) -> set[str]:
    return {kind for kind, pattern in _ROLES.items() if pattern.search(visible(text))}


def clauses(request: str) -> list[str]:
    """Keep coordinate tuples and shared 'OCR and barcode' stages together."""
    masked = visible(request)
    boundaries = list(re.finditer(r"[;!?\n]|\.(?!\d)|\b(?:while|whereas|but)\b", masked, re.I))
    starts, ends = [0] + [match.end() for match in boundaries], [match.start() for match in boundaries] + [len(request)]
    parts: list[str] = []
    for start, end in zip(starts, ends, strict=True):
        text = request[start:end].strip()
        if not text:
            continue
        masked = visible(text)
        cut = None
        for match in re.finditer(r",|\band\b", masked, re.I):
            left, right = masked[:match.start()], masked[match.end():]
            if left.count("[") != left.count("]") or left.count("(") != left.count(")"):
                continue
            if not roles(left) or not roles(right) or roles(left) == roles(right):
                continue
            right_action = bool(re.match(r"\s*(?:also\s+)?(?:read|decode|detect|count|recognize|extract)\b", right, re.I))
            if (_SCOPE.search(left) and (_SCOPE.search(right) or right_action)) or (_ACTION.search(left) and right_action):
                cut = match
                break
        if cut:
            parts.extend(clauses(text[:cut.start()]))
            parts.extend(clauses(text[cut.end():]))
        else:
            parts.append(text)
    return parts


def clauses_for_branch(request: str, kind: str) -> list[str]:
    """Return scoped clauses with original literals for a task kind.

    Initial unscoped clauses remain common. A following clause inherits preceding
    task names. Shared reader clauses remain shared: callers must ask for scope
    when a global comparison has several eligible reader branches.
    """
    selected: list[str] = []
    previous: set[str] = set()
    for text in clauses(request):
        named = roles(text)
        effective = named or previous
        if not effective or kind in effective:
            selected.append(text)
        if named:
            previous = named
    return selected


def branch_request(request: str, kind: str) -> str:
    return "; ".join(clauses_for_branch(request, kind))
