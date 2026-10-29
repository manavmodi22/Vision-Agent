"""Bind requested preprocessing to actual inference image paths and their order."""
import re
from dataclasses import dataclass

from agent.graph_language import clauses, roles, visible
from agent.preprocessing_fidelity import _crop_values, _resize_values
from spec.authoring import (
    BarcodeNode,
    CropNode,
    DetectNode,
    GraphCandidate,
    OCRNode,
    ResizeNode,
    SampleNode,
)

_CROP = re.compile(r"\bcrop(?:ping)?\b|\b(?:left|right|top|bottom|upper|lower)\s+half\b", re.I)
_RESIZE = re.compile(r"\b(?:resize|resizing|rescale|scale|enlarge|resolution|dimensions)\b|\b(?:width|height)(?=\s*[=:]?\s*\d)|\b(?:at|to|using|use)\s+\d+\s*(?:x|×|by)\s*\d+", re.I)
_FULL = re.compile(r"\b(?:full[- ](?:frame|image)|whole\s+(?:frame|image)|entire\s+(?:frame|image)|uncropped)\b", re.I)
_NEGATION = r"\b(?:do\s+not|don't|never|without|no|skip|omit|neither)\s+(?:any\s+)?"
_NO_CROP = re.compile(_NEGATION + r"(?:(?:resiz(?:e|es|ing)|rescal(?:e|ing)|scaling)\s+(?:or|and|nor)\s+)?crop(?:s|ping)?\b", re.I)
_NO_RESIZE = re.compile(_NEGATION + r"(?:crop(?:s|ping)?\s+(?:or|and|nor)\s+)?(?:resiz(?:e|es|ing)|rescal(?:e|ing)|scaling)\b|\b(?:original|native)\s+(?:resolution|dimensions|size)\b", re.I)


@dataclass(frozen=True)
class Transform:
    kind: str
    values: tuple[float, ...]


def _full_required(masked: str) -> bool:
    # 'Left half of the full frame' names a coordinate basis, not a full-frame branch.
    basis_removed = re.sub(r"\bhalf\s+of\s+(?:the\s+)?(?:full|whole|entire)[- ](?:frame|image)\b", "half of input image", masked, flags=re.I)
    return bool(_FULL.search(basis_removed))


def _requested(text: str) -> list[Transform]:
    masked = visible(text)
    masked = re.sub(r"\b(resize|rescale|enlarge|scale)\s+(?:that|the|this|existing|current)\s+crop\b", r"\1 image", masked, flags=re.I)
    crop_match, resize_match = _CROP.search(masked), _RESIZE.search(masked)
    crop_requested = crop_match is not None and not _NO_CROP.search(masked)
    resize_requested = resize_match is not None and not _NO_RESIZE.search(masked)
    if crop_requested and _full_required(masked):
        raise ValueError("The branch requests both a crop and the full frame; clarify its image scope")
    if crop_requested and (re.search(r"\b(?:within|inside|relative to|of)\s+(?:the\s+)?(?:saved\s+)?(?:zone|lane|region|polygon|object|box)\b", masked, re.I)
        or any(not re.match(r"(?:(?:the|its|each|every)\s+)?(?:(?:full|input|original|current|cropped)\s+)?(?:frame|image|crop|view)\b", match.group(1), re.I)
               for match in re.finditer(r"\bhalf\s+of\s+([^.;\n]+)", masked, re.I))):
        raise ValueError("Supply crop coordinates relative to the input image; object or zone-relative halves are ambiguous")
    if resize_requested and re.search(r"\b(?:letterbox|padding|pad|fit\s+(?:inside|within)|(?:keep|preserve|maintain)\s+(?:the\s+)?aspect\s+ratio)\b", masked, re.I):
        raise ValueError("This resize supports exact pixel dimensions; clarify unsupported aspect-preserving fit or padding")
    operations: list[tuple[int, Transform]] = []
    if crop_requested:
        box = _crop_values(masked)
        if box is None:
            raise ValueError("Specify exact normalized crop coordinates or a clear image half; do not invent a crop")
        assert crop_match is not None
        operations.append((crop_match.start(), Transform("crop", box)))
    if resize_requested:
        size = _resize_values(masked)
        if size is None:
            raise ValueError("Specify both resize width and height; do not invent dimensions")
        assert resize_match is not None
        operations.append((resize_match.start(), Transform("resize", tuple(size))))
    operations.sort(key=lambda pair: pair[0])
    if len(operations) == 2 and re.search(r"\bafter\b", masked[operations[0][0]:operations[1][0]], re.I):
        operations.reverse()
    return [operation for _, operation in operations]


def _chain(graph: GraphCandidate, consumer: DetectNode | OCRNode | BarcodeNode) -> tuple[list[Transform], set[str]]:
    nodes = {node.id: node for node in graph.nodes}
    reference, visited, operations = consumer.image, set[str](), list[Transform]()
    while True:
        owner = reference[1:].split(".")[0]
        if owner in visited or owner not in nodes:
            raise ValueError("The inference image path is missing or cyclic")
        visited.add(owner)
        node = nodes[owner]
        if isinstance(node, SampleNode):
            if reference != f"${owner}.frame":
                raise ValueError("The image path must use the sampled frame output")
            return list(reversed(operations)), visited - {owner}
        if not isinstance(node, (CropNode, ResizeNode)) or reference != f"${owner}.image":
            raise ValueError("Only sampled images and crop/resize image outputs may feed inference")
        operations.append(Transform("crop", node.box) if isinstance(node, CropNode)
                          else Transform("resize", (node.width, node.height)))
        reference = node.image


def validate_transforms(graph: GraphCandidate, request: str) -> None:
    consumers = [node for node in graph.nodes if isinstance(node, (DetectNode, OCRNode, BarcodeNode))]
    expected: dict[str, list[Transform]] = {node.id: [] for node in consumers}
    forbidden: dict[str, set[str]] = {node.id: set() for node in consumers}
    previous: list[str] = []
    for text in clauses(request):
        masked, task_kinds = visible(text), roles(text)
        named = [node.id for node in consumers if re.search(r"(?:\b(?:block|node|branch)\s+|`)" + re.escape(node.id) + r"(?![\w-])", masked)]
        possible = named or [node.id for node in consumers if node.type in task_kinds]
        if not task_kinds and not named:
            possible = [node.id for node in consumers] if len(consumers) == 1 else previous
        operations = _requested(text)
        blocked = ({"crop"} if _NO_CROP.search(masked) or _full_required(masked) else set()) | ({"resize"} if _NO_RESIZE.search(masked) else set())
        if blocked and not task_kinds and not named and not re.search(r"\b(?:it|that\s+branch|this\s+branch)\b", masked, re.I):
            possible = [node.id for node in consumers]
        if operations or blocked:
            if not possible:
                raise ValueError("Identify which detector or reader should receive the crop/resize; the branch is ambiguous")
            if not named and any(sum(node.type == kind for node in consumers) > 1 for kind in task_kinds):
                raise ValueError("Multiple readers or detectors share that task; identify the intended branch before preprocessing")
            for identifier in possible:
                for operation in operations:
                    # A named half restated as its numeric rectangle is one crop.
                    if not expected[identifier] or expected[identifier][-1] != operation:
                        expected[identifier].append(operation)
                forbidden[identifier].update(blocked)
        if task_kinds or named:
            previous = possible
    used: set[str] = set()
    for consumer in consumers:
        actual, identifiers = _chain(graph, consumer)
        used.update(identifiers)
        desired = expected[consumer.id]
        if any(operation.kind in forbidden[consumer.id] for operation in actual + desired):
            raise ValueError(f"The {consumer.type} branch forbids that crop/resize; preserve its requested image scope")
        if actual != desired:
            if any(operation.kind == "crop" for operation in actual + desired):
                raise ValueError(f"Preserve the requested crop coordinates and resize width and height on the {consumer.type} branch, in the requested order; clarify ambiguous branch scope")
            raise ValueError(f"Preserve the requested resize width and height on the {consumer.type} branch; do not omit or invent transforms")
    transforms = {node.id for node in graph.nodes if isinstance(node, (CropNode, ResizeNode))}
    if used != transforms:
        raise ValueError("Every crop/resize must feed the explicitly requested inference branch")
