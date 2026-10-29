# Conversational preprocessing edits

The existing refinement transaction accepts two additional typed patch kinds:

- `crop`: `crop_box: [x0, y0, x1, y1]`, finite normalized coordinates with positive
  area in the transform's input image.
- `resize`: `width` and `height`, integer pixel dimensions from 1 through 8192.

Both use the existing optional `block_id` and `scope` fields. Scope defaults to all
candidate alternatives. A block ID identifies an existing transform of the same
kind or an existing detector, OCR reader, barcode reader, or visual judge. Without
an ID there must be one image-consuming inference block. Ambiguous targets require
a question; a model cannot silently select one branch.

The pure target resolver follows only the chosen consumer's image-preprocessing
chain. A unique existing transform of the requested kind is updated; if absent,
one is inserted directly before the consumer. Multiple transforms of that kind
require an explicit transform ID. Shared preprocessing is copied along the selected
branch before modification, preserving other consumers and their original nodes.
A shared transform cannot itself be the target without choosing a consumer branch.
Model IDs, detector classes, comparison values, event sinks, source paths, and
unrelated branches remain unchanged.

The model must preserve user-supplied normalized rectangles and explicit resize
dimensions. Clear left/right/top/bottom half requests have exact normalized values.
Unspecified crop coordinates, ambiguous coordinate frames, invented dimensions,
and unrelated or partially applied compound changes are rejected before execution.
The parameters describe preprocessing, not new annotations or model-quality gains.

The existing refinement pipeline validates the complete candidate, previews every
affected alternative, checks concurrent changes, then commits and invalidates old
evaluation/approval evidence. No model or reader is added, and existing inference
block IDs and model parameters remain unchanged. Software tests cover typed bounds, target
resolution, branch preservation, literal fidelity, real fixture crop/resize output,
preview failure, and conflict behavior. Actual local-planner and native interaction
evidence is separate.
