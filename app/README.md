# VisionApp native shell

Build and test on Apple silicon with the macOS command-line SDK:

```sh
swift build --package-path app
app/test-native.sh
# With full Xcode installed, the XCTest target is also available:
swift test --package-path app
VISION_REPO_ROOT="$PWD" app/.build/debug/VisionApp
```

The portable `dist/VisionApp.app` launches its bundled Python runtime. For the
current checkout and `.venv/bin/python`, build and open the separate development app:

```sh
./scripts/build_app.sh --development
open dist/VisionApp-Development.app
```

The development bundle is rebuilt from a clean staging directory and never
reuses the portable bundle’s PythonRuntime or overwrites `dist/VisionApp.app`. Override `VISION_DATA_DIR` and `VISION_SOCKET` to isolate work.
An existing engine is accepted only when workspace, interpreter and source identity
match. The app terminates only its own engine; the engine also watches its parent.

The generated bundle uses `Info.plist`; signing/notarization are distribution
steps, not implied by a successful SwiftPM build.

Apple Vision works without opening the GUI:

```sh
app/.build/debug/VisionApp --analyze-image /absolute/path/to/label.png
```

The output contains `texts` and `barcodes`. Python receives the executable path
through `VISION_APP_BINARY` when the application supervises the engine.

Use the optional generated-fixture starter in **New project** to exercise import, template compilation,
preview, reviewed labels, evaluation, explicit deployment approval, local runs and
event evidence. Synthetic scores do not measure warehouse accuracy. Real pallet
and damage inference requires configured local OWLv2 weights; planning requires a
loaded planner at the configured local model server. OCR/barcodes use Apple Vision.

The Review screen starts a bounded local training job after a separate approval,
when the engine advertises a training backend. It displays status and adds the
trained model as a candidate; a new evaluation is required before deployment.
Camera/screen capture and timestamp-paced recorded-video replay are available as
bounded sessions. Recorded replay is verified; camera/screen hardware and permission
flows still need validation. Alert destinations are explicitly configured.

The command-line SDK on the initial Mac has no XCTest module. `--self-test` runs
the HTTP framing, malformed response, letterbox, normalized box and JSON wire
checks without XCTest; the XCTest source remains for full Xcode environments.


The primary workspace is **Agent**. Home accepts a goal and media, creates a project,
and starts the durable build. Conversation and actual progress stay beside the
generated application preview. Label review, evaluation and deployment are contextual
checkpoints. See [the interaction contract](../docs/native-agent-workspace.md).

Dataset is a secondary tool for draw/select/move/resize and review. Changes autosave
with revision checks. Undo/redo, zoom/pan, COCO import/export, snapshots and validation
selection remain available. Prediction overlays stay distinct from reviewed labels.

Workflow provides schema-backed block creation/removal, upstream-port connection
pickers and parameter editing. Save validates the graph and invalidates earlier
evaluation evidence. Run on new media keeps production input separate from the
training/evaluation dataset. Alerts has explicit destination review and delivery
receipts for webhook, SMTP and MQTT; credentials are write-only in the UI.

OCR and barcode previews retain actual reader regions, raw Unicode values and
execution identity separately from object annotations. See [reading evidence](reading-evidence.md)
for the compatible CLI protocol, correction behavior and validation boundaries.
