# Native describe-to-app acceptance

## Final packaged build

`final-build.json` and `final-build-window.jpg` record the final `c19fac…` package
using Qwen3-14B Q4_K_M and actual OWLv2 inference on NVIDIA Warehouse 026.
From Home, the goal requested people counts, boxes, and saved crops whenever at
least one person appears, at confidence 0.2. One actual local-model call produced
the correct whole-image graph and a five-image preview with four person predictions.
Planning, compilation and preview took 63.47 seconds in this run. Completion text
describes the compiled graph. The agent then prepared 20 unreviewed annotation
rows and stopped at review. Zero event records, evaluations or deployment approvals
were created. This verifies software behavior; it does not measure detection accuracy.

Earlier functional evidence is retained below with its original source identity.

Reference Mac: Apple M4 Pro, 48 GB. Tested with the real public NVIDIA Warehouse
026 recording. No real-data labels were marked reviewed and no real project was
approved for deployment during this test.

The native flow was Home → Try warehouse footage → Build my app, with the goal
“Count people in this warehouse footage and show bounding boxes.” It imported 20
frames, used the actual local planner/compiler/OWLv2 path, showed a five-image
preview, and created unverified annotation proposals. The user did not select a
model, define classes, or assemble blocks.

“Lower confidence to 0.15” changed only the detector's `min_conf` from 0.4 to 0.15;
the rest of the graph was identical. The actual five-frame preview changed from
2 to 7 detections. These are observations, not unique people or accuracy scores.
Earlier label proposals were retained so possible human edits were not overwritten.

The review action opened the editable annotation canvas. Continuing without review
returned to the same agent checkpoint, with zero evaluations and no deployment.
The final native UI also retains the submitted request and previous preview while
an update runs. The larger preview was inspected in the packaged app.

- `acceptance.json`: counts, exact graph difference, and review/deployment state.
- `initial-build.json` and `refined-build.json`: actual persisted build records.
- `sample-source.json`: pinned public source, timestamps, license and video hash.
- `home-window.jpg`, `final-workspace-window.jpg`: native application screenshots.
- `annotation-review-window.jpg`: real editable label proposals.
- `refinement-in-progress-window.jpg`: conversation beside the previous result.

Window images crop only the blank padding returned by the screenshot API and are
resized for reading. Original PNG captures are retained alongside them.
# Spatial goal acceptance

`region-acceptance.json` records a second native flow on the real NVIDIA
Warehouse 026 sample: describe counting people inside region A, receive a request
for its missing boundary, draw and save A on the actual image, and resume the
original goal. The saved pipeline has only frame sampling, OWLv2 person
detection, the selected A boundary and per-region counts. It has no invented
event threshold. Evaluation uses count MAE with target 0.5.

The actual five-frame preview contains one person detection, in its fifth frame,
with region A count 1. The agent then pauses for review of 20 unverified proposal
images. No evaluation or deployment was created and no accuracy is claimed.
`region-drawn-window.jpg` and `region-result-window.jpg` show the actual native UI;
their original PNG captures retain the capture service's surrounding white padding.
The marked rectangle is a software acceptance region, not a validated warehouse
lane layout.


## Packaged compound refinement

`compound-refinement.json` records a real native conversation on bundled source
`4f94d391e5238170979135e9425e4212bd43d8e885d6c66f764264433c191ccb`.
The user requested 20% confidence and one frame per second while retaining region A.
One actual local-model call produced two typed edits, followed by MCP compilation
and real OWLv2 previews. The stored graph differs only in confidence 0.4→0.2 and
sampling 2→1 FPS. Region geometry, count behavior, evaluation target and annotation
hash are unchanged. Five actual preview frames contain five person predictions.
No evaluation, label approval, deployment or recorded run was created.

## Native annotation correction

After the compound refinement, a UI acceptance check added the missed visible
worker in the 33.00s image using the native box tool. Autosave advanced the dataset
to revision 3. Changing images and returning loaded the same saved normalized box
from `annotations.json`; it was not a prediction overlay. The image remains
unreviewed, because this was an agent-operated software check, not human label
approval. No evaluation or deployment was created. See `annotation-correction.json`
and `annotation-correction-window.jpg`. The earlier compound-refinement hashes
describe the dataset before this subsequent edit.
The native **Export COCO annotations** action then wrote
`annotation-correction.coco.json`: 20 images and three boxes, including the saved
correction with matching pixel coordinates. `annotation-export-window.jpg` records
the successful export. Exporting does not change review status.

`compound-refinement-window.jpg` shows the conversation, review checkpoint and
actual model output side by side. These are unreviewed predictions, not measured
warehouse accuracy. The original capture is retained as a PNG.
