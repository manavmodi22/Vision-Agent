# Native dataset and annotation workspace

Owner: native_app. The Dataset screen is the primary project authoring workspace;
chat and evaluation are separate secondary tasks. The grid shows actual imported
images, dimensions, split and review status. A class ontology controls label names
and display colours. Opening a sample enters a focused annotation editor with a
filmstrip, image viewport and object inspector.

`AnnotationCanvasView` is an AppKit NSView hosted by SwiftUI. It draws actual pixels,
ground-truth boxes and separate non-editable prediction overlays. Ground-truth
editing supports selection, eight resize handles, drag movement, box creation,
class reassignment and deletion. Canvas geometry operates in normalized image
coordinates; zoom and pan never change stored boxes. Selection is an index within
the current image. Edits are committed once per gesture so undo is meaningful.

`DatasetWorkspace` owns the current annotation, saved snapshot and undo/redo stack.
Every annotation mutation marks it unreviewed. Explicit review is a separate action.
Autosave debounces edits, submits the server revision, and preserves the draft if
saving conflicts or fails. Navigation flushes the pending image before switching.
Credentials and model invocation are unrelated to this workspace.

Canvas shortcuts: V select, B box, H pan, Space-drag temporary pan, Delete remove,
Command-Z undo, Shift-Command-Z redo, Left/Right adjacent image, F fit. Pinch zooms;
scroll pans; Option-scroll zooms at the pointer. Toolbar equivalents remain visible.

Validation: normalized geometry clamping, move/resize invariants, unchanged boxes
under viewport transformations, review-state transitions, revisioned request wire
keys, undo/redo, native build and UI interaction on a real image. Predictions are
never silently converted to reviewed ground truth.

The project retains its editor store across sidebar navigation. Navigation flushes
all changes, including edits made while an earlier save was in flight. A global
revision change triggers a fresh per-image load before new edits. Concurrent-save
conflicts preserve the local draft and require an explicit discard/reload. The app
waits for unsaved annotations on quit and keeps the window open if saving fails.

Validation completed: the root agent's native UI QA created and moved a person
box, inspected resize handles, exercised undo/redo and 125% zoom/Fit, navigated
away and back, and verified the saved normalized coordinates with reviewed=false.
A new pallet class was created and appeared in the annotation dropdown. Native
self-tests now include geometry clamping, hit testing, proposal preservation and
revision wire keys.
