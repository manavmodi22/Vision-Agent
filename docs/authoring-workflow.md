# CV authoring workflow

The primary workspace is the agent conversation and the application it builds.
The dataset and block editor are contextual tools for review and correction.
An inference overlay is one output of the agent's work; the agent must orchestrate
construction, testing and improvement. See [the product contract](agent-product-experience.md).

## Product references reviewed

- [Roboflow Agent](https://roboflow.com/agent): describes selecting models,
  constructing workflows, running them and querying evidence. These are vendor
  claims, not an independent performance assessment.
- [Published video walkthrough](https://roboflow.com/blog/annotating-video#how-to-use-the-roboflow-agent-for-video-tasks):
  inspected the goal composer and chat beside Preview/Editor/Deploy screenshots.
  This was a review of public product material, not a logged-in test of its agent.
- [Workflows AI Assistant](https://docs.roboflow.com/workflows/build/workflows-ai-assistant.md):
  chat beside an editable canvas, block settings, draft changes and explicit
  publication. The separation between editing and publishing is useful here.
- [Annotation tools](https://docs.roboflow.com/datasets/annotate/annotate.md):
  manual labeling, model-assisted labeling, review and annotation history.

This implementation uses its own native editor, local inference engine and MCP
server. Studying the product does not introduce a Roboflow runtime dependency.

## Default describe-to-app flow

1. Describe the desired outcome, add images/video or choose **Try warehouse footage**,
   and click **Build my app**. The agent creates the project and proposes the classes
   and workflow. There is no required manual class, model or block setup.
2. The agent asks for genuinely missing information or actual region boundaries,
   compiles the workflow and runs inference. Conversation and preview stay together.
3. Correct its proposed labels when requested and continue the same build. The agent
   evaluates candidates on reviewed images, presents failures, and can request
   bounded training. Evaluation and approval determine whether operation can start.
4. Describe changes in the conversation. Supported edits update the saved graph,
   preview affected candidates and preserve existing label corrections. Optional
   expert tools remain available for direct editing.

The real native acceptance evidence, including a saved box correction, is in
`artifacts/agent-experience/README.md`. These examples are functional checks, not
detector-accuracy measurements.

## Annotation and expert tools

1. Open an image, draw/select/move/resize boxes, reassign classes, undo/redo, and
   mark the image reviewed. Geometry is normalized xyxy in the original image.
2. Edit one image at a time with a dataset revision. A conflicting save returns
   HTTP409 and preserves the editor's local draft. Class renames update labels
   and reset affected images to unreviewed.
3. Request detector suggestions. Only empty, unreviewed images are eligible;
   existing manual labels and reviewed labels are preserved. Suggestions carry
   model/spec/image provenance and never become reviewed automatically.
4. Import/export COCO bounding boxes or create a dataset snapshot. Snapshots
   copy image bytes and labels so later edits cannot silently change a version.
   COCO imports validate image dimensions, references and box bounds. Imported
   labels require human review; crowd regions are rejected explicitly.
5. Edit the pipeline's typed block parameters. Every saved pipeline compiles;
   edits revoke stale evaluation/deployment evidence. Custom detector classes
   come from the user's ontology or explicit request.
6. Select 10–50 reviewed images as a holdout. The dataset can contain 5,000 images;
   the evaluation holdout is distinct from the larger annotation/training pool.

## Current limits

The native annotation tool currently supports bounding boxes and expected OCR
text. Polygon masks, keypoints, video track annotation and collaborative multiuser
assignment are not implemented. OWLv2 suggestions are model hypotheses. A local
VLM can answer a bounded visual question but cannot certify detection quality.
Training must be judged on a disjoint reviewed holdout; an optimizer step or a
successful model export is not proof of a useful custom detector.
