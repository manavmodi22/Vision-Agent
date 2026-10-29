"""Verify explicit preprocessing values and branch scope before any graph edit."""
import math
import re

from spec.models import PipelineSpec
from spec.preprocessing import IMAGE_CONSUMERS, image_chain, preprocessing_target
from spec.refinement import RefinementContext, RefinementPatch

_NUMBER = r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)"
_BOX = re.compile(r"[\[(]\s*(" + _NUMBER + r")\s*,\s*(" + _NUMBER + r")\s*,\s*(" + _NUMBER + r")\s*,\s*(" + _NUMBER + r")\s*[\])]")
_HALVES = {"left": (0., 0., .5, 1.), "right": (.5, 0., 1., 1.),
           "top": (0., 0., 1., .5), "upper": (0., 0., 1., .5),
           "bottom": (0., .5, 1., 1.), "lower": (0., .5, 1., 1.)}
_ROLE_PATTERNS = {
    "ocr": r"\b(?:OCR|printed[- ]text)\b",
    "barcode": r"\bbarcodes?\b",
    "detector": r"\b(?:detector|object[- ]detection)\b",
    "judge": r"\b(?:visual judge|VLM)\b",
}
_ROLE_KINDS = {"ocr": {"ocr"}, "barcode": {"barcode"},
               "detector": {"detect", "detect_open_vocab"}, "judge": {"vlm_judge"}}
_PRESERVED = re.compile(r"\b(?:keep|leave|preserve)\s+(?:the\s+)?[\w-]+(?:\s+(?:branch|crop|resize))?\s+unchanged\b", re.I)


def _visible(prompt: str) -> str:
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27', " ", prompt)


def _crop_values(prompt: str) -> tuple[float, ...] | None:
    turns = re.split(r"\nUser clarification:\s*", prompt, flags=re.I)
    if len(turns) > 1:
        for turn in reversed(turns):
            if (value := _crop_values(turn)) is not None:
                return value
        return None
    boxes = {tuple(float(value) for value in match.groups()) for match in _BOX.finditer(prompt)}
    boxes.update(_HALVES[match.group(1).lower()] for match in re.finditer(
        r"\b(left|right|top|bottom|upper|lower)\s+half\b", prompt, re.I))
    if len(boxes) > 1:
        raise ValueError("The crop request contains different rectangles; identify one crop and its intended bounds")
    return next(iter(boxes)) if boxes else None


def _resize_values(prompt: str) -> tuple[int, int] | None:
    turns = re.split(r"\nUser clarification:\s*", prompt, flags=re.I)
    if len(turns) > 1:
        for turn in reversed(turns):
            if (value := _resize_values(turn)) is not None:
                return value
        return None
    sizes = {(int(match.group(1)), int(match.group(2))) for match in re.finditer(
        r"(?<![\w.])([-+]?\d+)\s*(?:x|×|by)\s*([-+]?\d+)(?![\w.])", prompt, re.I)}
    widths = {int(match.group(1)) for match in re.finditer(r"\bwidth\s*(?:of|to|=|:)?\s*([-+]?\d+)\b", prompt, re.I)}
    heights = {int(match.group(1)) for match in re.finditer(r"\bheight\s*(?:of|to|=|:)?\s*([-+]?\d+)\b", prompt, re.I)}
    if len(widths) > 1 or len(heights) > 1:
        raise ValueError("Specify one width and height for the intended resize")
    if widths and heights:
        sizes.add((next(iter(widths)), next(iter(heights))))
    if len(sizes) > 1:
        raise ValueError("The resize request contains different sizes; identify one resize and its dimensions")
    return next(iter(sizes)) if sizes else None


def _validate_target(patch: RefinementPatch, prompt: str, candidate: PipelineSpec, consumer_id: str) -> None:
    consumers = [block for block in candidate.blocks if block.type in IMAGE_CONSUMERS]
    target = next(block for block in consumers if block.id == consumer_id)
    names = [re.escape(consumer_id)]
    if patch.block_id:
        names.append(re.escape(patch.block_id))
    names.extend(pattern for role, pattern in _ROLE_PATTERNS.items() if target.type in _ROLE_KINDS[role])
    target_name = "(?:" + "|".join(names) + ")"
    if re.search(r"\b(?:keep|leave|preserve)\s+(?:the\s+)?" + target_name + r"(?:\s+branch)?\s+unchanged\b|\b(?:do not|don't)\s+(?:change|edit|resize|crop)\s+(?:the\s+)?" + target_name + r"\b|\b(?:not|except|excluding)\s+(?:the\s+)?" + target_name + r"\b", prompt, re.I):
        raise ValueError("The preprocessing edit targets a branch the user asked to preserve")
    # A supplied graph ID is not permission to select a branch arbitrarily.
    if patch.block_id and re.search(r"(?<![\w-])" + re.escape(patch.block_id) + r"(?![\w-])", prompt):
        return
    visible = _visible(prompt)
    roles: set[str] = set()
    # Excluded branches are not a positive target designation.
    visible = _PRESERVED.sub(" ", visible)
    for role, pattern in _ROLE_PATTERNS.items():
        mentions = list(re.finditer(pattern, visible, re.I))
        if any(not re.search(r"\b(?:not|except|excluding)\s+(?:the\s+)?$", visible[:match.start()], re.I) for match in mentions):
            roles.add(role)
    if roles:
        plausible = [block for block in consumers if any(block.type in _ROLE_KINDS[role] for role in roles)]
        if len(plausible) == 1 and plausible[0].id == consumer_id:
            return
        raise ValueError("Identify the exact detector or reader block for this preprocessing change")
    if len(consumers) == 1:
        return
    if re.search(r"\b(?:read|reader|reading)\b", visible, re.I):
        readers = [block for block in consumers if block.type in {"ocr", "barcode"}]
        if len(readers) == 1 and target.id == readers[0].id:
            return
    raise ValueError("Multiple image consumers exist; name the intended detector or reader instead of choosing a branch")


def _validate_order(patches: list[RefinementPatch], prompt: str, context: RefinementContext) -> None:
    """Simulate only image-path ordering; inference and graph mutation stay elsewhere."""
    tokens = list(re.finditer(r"\b(?:crop(?:ping)?|resize|resizing|rescale)\b|\b(?:left|right|top|bottom|upper|lower)\s+half\b", prompt, re.I))
    order: tuple[str, str] | None = None
    for left, right in zip(tokens, tokens[1:], strict=False):
        first = "resize" if left.group().lower().startswith("resiz") or left.group().lower() == "rescale" else "crop"
        second = "resize" if right.group().lower().startswith("resiz") or right.group().lower() == "rescale" else "crop"
        between = prompt[left.end():right.start()]
        if first != second and re.search(r"\b(?:then|before|after)\b", between, re.I):
            order = (second, first) if re.search(r"\bafter\b", between, re.I) else (first, second)
    if order is None:
        return
    for index, candidate in enumerate(context.candidates):
        nodes = {node.id: node for node in candidate.blocks}
        chains: dict[str, list[tuple[str, str]]] = {}
        touched: dict[str, dict[str, set[str]]] = {}
        for number, patch in enumerate(patches):
            if patch.kind not in {"crop", "resize"} or (patch.target_scope() == "selected" and index != context.selected_candidate_index):
                continue
            target = preprocessing_target(candidate, patch.kind, patch.block_id)
            chain = chains.setdefault(target.consumer_id, [(identifier, nodes[identifier].type)
                for identifier in reversed(image_chain(nodes[target.consumer_id], nodes))])
            identifier = target.transform_id
            if identifier is None:
                existing = [name for name, kind in chain if kind == patch.kind]
                identifier = existing[0] if existing else f"$new_{number}"
                if not existing:
                    chain.append((identifier, patch.kind))  # New transforms insert immediately before the consumer.
            touched.setdefault(target.consumer_id, {}).setdefault(patch.kind, set()).add(identifier)
        for consumer_id, operations in touched.items():
            if set(operations) != {"crop", "resize"}:
                continue
            if any(len(identifiers) != 1 for identifiers in operations.values()):
                raise ValueError("Identify one crop and resize when requesting their order")
            identifiers = [identifier for identifier, _ in chains[consumer_id]]
            first_id, second_id = next(iter(operations[order[0]])), next(iter(operations[order[1]]))
            if identifiers.index(first_id) >= identifiers.index(second_id):
                raise ValueError("Preserve the requested crop/resize order. Correct new patch ordering; existing transforms cannot be reordered by refinement, so ask instead.")


def validate_preprocessing_fidelity(patches: list[RefinementPatch], prompt: str, context: RefinementContext) -> None:
    visible = _PRESERVED.sub(" ", _visible(prompt))
    # Evidence crops are outputs, not preprocessing instructions.
    visible = re.sub(r"\b(?:save|store|record|retain)\s+(?:an?\s+|the\s+)?(?:evidence\s+)?crops?\b", " ", visible, flags=re.I)
    crop_disabled = bool(re.search(r"\b(?:do not|don't|never|without|no)\s+crop(?:ping)?\b", visible, re.I))
    resize_disabled = bool(re.search(r"\b(?:do not|don't|never|without|no)\s+(?:resize|resizing|rescale)\b", visible, re.I))
    crop_requested = not crop_disabled and bool(re.search(r"\bcrop(?:ping)?\b|\b(?:left|right|top|bottom|upper|lower)\s+half\b", visible, re.I))
    resize_requested = not resize_disabled and bool(re.search(r"\b(?:resize|resizing|rescale|resolution|dimensions)\b", visible, re.I))
    if crop_requested and (re.search(
        r"\b(?:within|relative to|inside|of)\s+(?:the\s+)?(?:saved\s+)?(?:zone|lane|region|polygon|object|box)\b", visible, re.I)
        or any(not re.match(r"(?:(?:the|its)\s+)?(?:(?:full|input|original|current|cropped)\s+)?(?:frame|image|crop|view)\b", match.group(1), re.I)
               for match in re.finditer(r"\bhalf\s+of\s+([^.;\n]+)", visible, re.I))):
        raise ValueError("Crop bounds must identify the transform input image; object or saved-zone-relative crops need explicit geometry")
    if resize_requested and re.search(r"\b(?:letterbox|padding|pad|fit\s+(?:inside|within)|(?:keep|preserve|maintain)\s+(?:the\s+)?aspect\s+ratio)\b", visible, re.I):
        raise ValueError("This resize supports exact pixel dimensions; aspect-preserving padding or fit behavior needs a separate supported transform")
    crops = [patch for patch in patches if patch.kind == "crop"]
    sizes = [patch for patch in patches if patch.kind == "resize"]
    if crops and not crop_requested:
        raise ValueError("No crop was requested; preserve the existing image scope")
    if sizes and not resize_requested:
        raise ValueError("No resize was requested; preserve existing image dimensions")
    box = _crop_values(visible) if crop_requested else None
    size = _resize_values(visible) if resize_requested else None
    if crop_requested and (not crops or box is None):
        raise ValueError("The crop request needs explicit normalized bounds or a clear left/right/top/bottom half; do not omit it or invent geometry")
    if resize_requested and (not sizes or size is None):
        raise ValueError("The resize request needs explicit width and height; do not omit it or invent dimensions")
    for patch in [*crops, *sizes]:
        if patch.kind not in {"crop", "resize"}:
            continue
        if patch.kind == "crop" and (box is None or patch.crop_box is None or any(
                not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
                for actual, expected in zip(patch.crop_box, box, strict=True))):
            raise ValueError("Preserve the user's exact crop bounds; do not substitute a different region")
        if patch.kind == "resize" and (patch.width, patch.height) != size:
            raise ValueError("Preserve the user's exact resize width and height")
        indices = [context.selected_candidate_index] if patch.target_scope() == "selected" else range(len(context.candidates))
        for index in indices:
            candidate = context.candidates[index]
            target = preprocessing_target(candidate, patch.kind, patch.block_id)
            _validate_target(patch, prompt, candidate, target.consumer_id)
            if patch.kind == "crop" and target.input_is_cropped and not re.search(
                r"\b(?:input image|current crop|already cropped|cropped image)\b", visible, re.I):
                raise ValueError("This crop receives an already-cropped image; specify bounds in that input image or select the intended earlier crop")
    _validate_order(patches, visible, context)
