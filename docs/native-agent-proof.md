# Native evidence and correction flow

The Agent artifact pane presents completed evaluation evidence from BuildStatus: all candidates, each declared metric, measured value, target direction, reviewed image count, warnings, and the agent-selected candidate. Comparison inspection does not change the orchestrator's selected candidate or imply approval.

Worst failures show the actual image and reported false positives, missed objects, count error, or expected/observed text. Correct this image resolves the exact imported image path and opens the existing revisioned annotation editor. Corrections preserve proposal provenance, clear human-review status only when labels change, and return to the same Agent build after explicit review.

When the selected candidate misses its target, the Agent offers correction, any server-authorized two-minute training attempt, and an explicit deployment override review. The approval sheet shows measured value, target and sample count, requires a reason for a miss, and calls the human deployment API. Only then can the existing build continue. No comparison row, label edit or tool result grants approval.

OCR/barcode review is inferred from actual `ocr`/`barcode` blocks, not the project's creation preset. Both custom projects and legacy projects expose expected-text editing. Text-entry UI retains line breaks while editing; normalized values are stored through the same annotation object and never remove its proposal provenance.

Region definitions are another contextual input: a define_zones checkpoint opens the region editor and explicit Save regions and continue building returns to the original goal. Unconfirmed backend defaults must not be displayed as confirmed user geometry.
