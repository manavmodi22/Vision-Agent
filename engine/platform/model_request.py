"""Conservative exact-ID experimental requests; no LLM-granted eligibility."""
import hashlib
import re


def request_hash(request: str) -> str:
    return hashlib.sha256(request.encode()).hexdigest()


def explicit_model_ids(request: str, registered_ids: list[str]) -> list[str]:
    """Recognize affirmative use/compare commands naming an exact registered ID.

    Quoted data is ignored unless the whole quoted value is a registered model ID.
    A later negative mention cancels an earlier request for the same model.
    """
    known = set(registered_ids)

    def quoted(match: re.Match[str]) -> str:
        value = match.group(1)
        return value if value.removeprefix("model.") in known else " "

    visible = re.sub(r'["`\u201c\u201d]([^"`\u201c\u201d]*)["`\u201c\u201d]', quoted, request)
    visible = re.sub(r"(?<!\w)'([^'\n]*)'(?!\w)", quoted, visible)
    selected: set[str] = set()
    for clause in re.split(r"[;\n.!?]+(?![A-Za-z0-9_-])", visible):
        clause = re.sub(r"^\s*User clarification:\s*", "", clause, flags=re.IGNORECASE)
        for identifier in registered_ids:
            pattern = r"(?<![A-Za-z0-9_-])(?:model\.)?" + re.escape(identifier) + r"(?![A-Za-z0-9_-])"
            for mention in re.finditer(pattern, clause):
                prefix = clause[:mention.start()].lower()
                for model_id in registered_ids:
                    prefix = re.sub(r"(?:model\.)?" + re.escape(model_id), " @ ", prefix)
                negative = re.search(r"\b(?:not|never|avoid|skip|exclude|without|instead of)\b|n['\u2019]t\b", prefix)
                command = re.match(r"\s*(?:please\s+|i\s+(?:want|would like)\s+to\s+)?(?:use|try|compare|test|benchmark|evaluate|include|select|run)\b", prefix)
                if negative:
                    selected.discard(identifier)
                elif command:
                    # Only model-object lists after the direct command grant scope;
                    # e.g. 'Use the label local-x' remains data, not model selection.
                    objects = prefix[command.end():]
                    if re.fullmatch(r"(?:\s|@|,|\b(?:the|model|models|checkpoint|checkpoints|experimental|and|with|versus|vs|against|to)\b)*", objects):
                        selected.add(identifier)
    return sorted(selected)
