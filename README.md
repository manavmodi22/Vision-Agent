# VisionApp for Mac

A native Mac app where you describe a vision task and the agent builds and tests
a working application on your images or video. The conversation stays beside
the generated preview. Label corrections, evaluation, and improvements continue
in that same build. Inference and storage run locally. External alert delivery is opt-in.
The engine uses a private Unix socket; planner and vision-model servers use localhost.

This is a development build. See [implementation status](docs/status.md),
[authoring workflow](docs/authoring-workflow.md), and [data/model provenance](docs/data-and-models.md).
The [agent platform revision](docs/agent-platform-revision.md) records the updated
architecture and implementation gaps.

The capability catalog can now create a reviewable installation plan for the
pinned YOLOX-s ONNX detector. Review its source, download size and license
declaration, then explicitly install and validate it. The completed smoke test
proves local execution; project quality still needs reviewed examples. YOLOX uses
its fixed COCO classes and does not supply pallet, forklift or damage detection.

## Open the app

Open `dist/VisionApp.app` after building it with the commands below. App bundles,
downloaded model weights and full datasets are not stored in this repository.

1. Describe the outcome, attach images/video or choose **Try warehouse footage**,
   and click **Build my app**. For example: “Count people in this warehouse footage
   and show bounding boxes.” No project-name, class, or model setup is required.
2. Watch the saved build plan and actual activity beside the generated preview.
   The agent interprets the goal, compiles a typed workflow, and executes inference
   on your samples. Expand the activity to inspect recorded calls and artifacts.
3. Use **Correct this image** or the agent's review request to open annotation
   review, then return to the conversation and **Continue building**. Proposals remain unreviewed until a person
   checks them. Draw/select/move/resize, undo/redo, and COCO import/export are available.
   Reading workflows also support editable four-corner text regions, exact transcripts,
   and explicit copying of OCR/barcode predictions into unreviewed labels. Use
   **Export all labels** to preserve text regions and provenance; COCO exports object boxes.
4. The agent evaluates candidates on reviewed examples and reports the measured
   result. Bounded local training requires an explicit approval; a trained candidate
   is evaluated against the same holdout. Changed inputs invalidate stale evidence.
5. Review the evidence before recorded operation. Sample scores cannot qualify an
   app for quality promotion: reserve independent examples, label them, and run the
   selected candidate once. A bounded local trial needs a written reason and keeps
   external alert delivery disabled. New-media runs preserve the development dataset.
6. Refine the goal in the conversation. Workflow, dataset, zones and evaluation
   remain available as tools. Events store observations/crops; optional webhook,
   SMTP and MQTT alerts require explicit configuration. Credentials use Keychain.

The built-in warehouse sample is 20 unreviewed frames from NVIDIA's real Warehouse
026 recording, with pinned source, license and hash provenance. Existing warehouse
projects and their annotations remain available.

Repeated frames are observations, not unique-object counts. The separate synthetic
pallet walkthrough tests software behavior using geometric fixtures; it does not
measure warehouse detection accuracy.

## Develop

Apple silicon Mac, macOS 15+, Python 3.12 and Swift command-line tools are required.
No full Xcode installation was needed for this build.

```sh
VISION_PYTHON=/path/to/python3.12 ./scripts/bootstrap.sh
./scripts/build_app.sh
open dist/VisionApp.app
```

The default build bundles a relocatable Python runtime and locked dependencies.
Use the separate development bundle for faster checkout-based iteration:

```sh
./scripts/build_app.sh --development
open dist/VisionApp-Development.app
```

This creates a fresh `VisionApp-Development.app` using the current checkout and
virtual environment; keep both in place. It does not overwrite `dist/VisionApp.app`
or reuse its bundled Python runtime. Local bundles are ad-hoc signed, not notarized.
See [packaging](docs/packaging.md).

```sh
# Start the measured official Qwen3-14B planner from the local model cache.
.venv/bin/python -m scripts.start_model_server
# A different licensed GGUF can be supplied with --model /path/to/model.gguf.
# Reproduce public NVIDIA sample acquisition and project import.
.venv/bin/python -m scripts.prepare_nvidia
# Tests and supported native checks.
.venv/bin/python -m pytest -q
.venv/bin/mypy spec engine agent mcp_server evals
.venv/bin/ruff check .
./app/test-native.sh
# Published synthetic-label baseline, separate from user approval.
.venv/bin/python -m scripts.benchmark_nvidia
```

Planner model provenance, the paired comparison, memory measurements, and the
current validation gate are recorded in [planner selection](docs/planner-selection.md).

`app/test-native.sh` runs executable parser/geometry/wire checks. XCTest sources
are also present; `swift test` needs an SDK with XCTest (absent from this Mac's
CommandLineTools installation).

## Layout and protocols

`spec/` owns the versioned schema. `engine/` owns validated block execution, local
models, evaluation, training, jobs and storage. `mcp_server/` provides typed stdio
tools. `agent/` uses Pydantic AI for a small typed pattern decision, then compiles
through MCP and previews it. The state machine and engine enforce gates, not the
model. `app/` owns UI and Apple Vision. Prompts never become executable code.

Environment overrides: `VISION_DATA_DIR`, `VISION_SOCKET`, `VISION_MODELS_DIR`,
`VISION_APP_BINARY`, `VISION_REPO_ROOT`. Default data:
`~/Library/Application Support/VisionApp`; default socket:
`/tmp/visionapp-<uid>/<workspace-hash>-<source-hash>.sock` (0700 directory, 0600
socket). The native supervisor verifies the engine's workspace, interpreter and
source identity before accepting it.

MCP debugging: `.venv/bin/python -m mcp_server --help`. Approval, data deletion and
alert destination changes are never exposed to the model as tools.

## Evidence and limitations

Actual OWLv2 proposals, native OCR, local Cosmos image judgement, pretrained
RT-DETRv2 training/save/reload and real planner/MCP calls are exercised separately
from synthetic software tests. The NVIDIA
30-frame person/forklift benchmark scored 85.9% precision and 39.2% recall; the 80%
recall gate **failed**. No pallet/damage/barcode accuracy or production FPS is
claimed. Full failure details and exact sample provenance are in `artifacts/`.

A short pretrained specialization run scored 61.7% precision and 77.3% recall on 10
held-out synthetic frames; the 80% recall target still failed. These are disjoint
images from correlated footage, not an independent scene benchmark. See
`artifacts/vision-verification/rtdetr-pretrained-specialization.json`.
