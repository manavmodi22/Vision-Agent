# Capability discovery and reviewed provisioning

Owner: core engine. Neutral DTOs are in `spec/capabilities.py`; engine discovery
lives in `engine/capabilities`. `GET /capabilities` returns a machine-readable
catalog through `engine/api/capability_routes.py`. Root owns router integration;
the native app reads the same DTO used by orchestration.

Stable IDs are `block.<registry type>`, `model.<registry model id>`, and
`tool.<MCP tool name>`. Configured local servers have stable entries
`model.configured-planner` and `model.configured-vlm`, with their selected model
IDs and endpoint metadata in evidence. Unsupported proposals remain explicit.

Availability describes installation, not inference quality. `installation_ready`
means known prerequisites pass and a bounded validation experiment can be
attempted. `readiness` carries the scope and actual evidence; file presence and
server metadata never become inference-smoke claims. `callable` requires ready
evidence. Learned models with prerequisite checks alone remain `unchecked`.
Discovery does not alter existing run paths or deployment gates. A planner can
propose validation of an installed adapter without promoting it as proven.

The GET operation reads registry contracts, package metadata, bounded config and
manifest files, and bounded loopback `/models` responses. It never loads learned
weights, downloads, starts a server, runs a live LLM, or saves user data. The
synthetic color adapter may run a tiny CPU self-test, explicitly labelled as
software-only evidence. Unknown resource estimates stay null. Model licenses are
declared registry/manifest metadata unless evidence establishes more.

YOLOX-s ONNX is now an implemented detector family with a reviewed provisioning
recipe. Other YOLO variants, SAM 3 and alternative OCR slots retain their explicit
unsupported status; an isolated probe does not make an adapter callable in the
app. Availability-to-install is reserved for implemented adapters with a known
installation path. Existing individual installers remain separate from the first
unified recipe below.

The catalog does not choose a license for the user's repository: its own source
and synthetic adapter are identified as project source with unspecified licensing.
Third-party declarations remain separate from local dataset/weight restrictions.

Orchestrator integration uses the synchronous
`validate_experiment_capabilities(service, required_ids)` for `block.*` and
`model.*` prerequisites. It permits installed-but-unchecked adapters for bounded
validation; it does not grant phase permissions, training or deployment approval.
MCP tool grants remain under the coded tool-authority checks. The API uses
`build_router(service)`; discovery calls `await build_catalog(service)`.

Verification: 111 focused catalog, MCP, model-output and reading-contract checks
passed. Subsequent metadata/licensing robustness changes were rechecked in the
catalog/MCP suite. Strict mypy and Ruff pass for the catalog boundary. A real
local inventory is saved in `artifacts/capability-catalog-local.json`; it performs
no learned-model inference or model downloads and is not a quality benchmark.


## First reviewed recipe: YOLOX-s ONNX

At verified provisioning runtime source
`2f0804da25ccbd6047d9dee2389127f13e3aa944b2596e1b0e7b577e1d5363a5`,
`model.yolox-s-onnx-coco` uses adapter `yolox-onnx` and ONNX Runtime's
`CPUExecutionProvider`. Its exact COCO vocabulary is closed: selecting this model
does not support arbitrary warehouse classes or silently translate forklift or
pallet into another class. Selected-detector prerequisite checks no longer demand
OWLv2 when the graph explicitly selects YOLOX.

The registry pins the [official release weights](https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx)
at **35,858,002 bytes**, SHA-256
`c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063`,
and the [repository license](https://raw.githubusercontent.com/Megvii-BaseDetection/YOLOX/6ddff4824372906469a7fae2dc3206c7aa4bbaee/LICENSE)
at source revision `6ddff4824372906469a7fae2dc3206c7aa4bbaee`. The two
artifacts total **35,869,373 bytes**. Apache-2.0 is the official repository
declaration; a separate asset license was not found in the inspected release.
This is scoped provenance, not independent legal verification. The repository
and application bundle do not redistribute the weights.

The native catalog can request an immutable plan containing exact sources,
expected hashes/sizes, target, license scope, dependencies and host readiness.
Only an explicit approval of that plan ID and hash starts a job. Discovery,
opening a saved plan and reopening job status do not download or infer.

| API | Effect |
| --- | --- |
| `GET /provisioning/options` | Read supported install/validate actions and blockers |
| `POST /provisioning/plans {model_id}` | Persist a concrete immutable review plan |
| `GET /provisioning/plans/{id}` | Read the saved plan |
| `POST /provisioning/jobs {plan_id, plan_hash, approved: true}` | Start the approved bounded operation |
| `GET /provisioning/jobs?model_id=...` and `GET /provisioning/jobs/{id}` | Recover durable progress, terminal result or error |
| `GET /provisioning/health/{id}` | Read a historical smoke receipt |

Jobs verify streaming size and SHA-256, install a new directory atomically, and
run a fixed generated black-image inference in a bounded subprocess. Callers
cannot supply URLs, paths, commands or package installation instructions. The
600-second job limit, read/deadline checks and subprocess output/time limits are
enforced. An existing differing installation is preserved and blocks overwrite.
Restart marks unfinished work interrupted and removes only owned staging;
retry needs a new explicit request. Active jobs are idempotent for the same plan,
and a completed job is reused only while its evidence remains current.

Installation and execution readiness remain separate. The current health receipt
binds installed bytes, runtime/source/dependency/host identity and the exact fixed
smoke request. A new failed validation clears current health while retaining the
historical receipt and verified weights. A successful black-image smoke proves
that this adapter executed on this host; its quality claim is explicitly `none`.
It cannot approve an application or promote a detector on user data.

Verified evidence, with original source checkpoints retained:

- [Fresh isolated API installation on `2f08`](../artifacts/provisioning/installation-2f08.json)
  completed in 13.773 seconds including official download and black-image smoke.
  Exact artifacts, mandatory approval, mismatched-hash rejection and active/
  completed job replay pass. The [original `f0d1` installation](../artifacts/provisioning/installation-f0d1.json)
  and its 4.318-second observation remain separate historical evidence.
- [Integrated adapter parity on `f0d1`](../artifacts/provisioning/adapter-parity-f0d1.json)
  matched all retained outputs on 30 NVIDIA Warehouse_016 synthetic frames.
  Published labels remain unreviewed. Diagnostic recall remains **59 / 112 =
  52.7%**, with 97 false positives; the prior recall gate still fails. This is
  adapter parity, not independent acceptance, a throughput benchmark or approval.
- [Actual Qwen/MCP construction on `2f08`](../artifacts/provisioning/agent-2f08.json)
  passed the exact original goal with one response and two real preview frames
  in 75.757 seconds. The [failed `f0d1` request](../artifacts/provisioning/agent-f0d1.json)
  and [captured operation](../artifacts/provisioning/agent-f0d1-operation.json)
  remain retained: a correct model decision was rejected by the old coordinated-
  negation guard. Neither construction result is a detector-quality benchmark.
- [The `2f08` full suite](../artifacts/provisioning/full-tests-2f08.log) passes
  **758 tests in 391.25 seconds**; strict mypy on 168 files and repository Ruff pass.
  The targeted event suites pass 112 checks in 4.37 seconds. Debug and Release
  native binaries each retain 204 software/decoding checks. Earlier
  [37-check provisioning software evidence](../artifacts/provisioning/software-validation-f0d1.json)
  uses explicitly mocked network/inference and is not an actual download receipt.
- [Candidate bundle verification](../artifacts/provisioning/bundle-2f08.json)
  passes relocation/imports, OCR/fixture inference, actual YOLOX real-image and
  black-image inference, and signatures. The [actual `f0d1` native installation](../artifacts/provisioning/native-installation-f0d1.json)
  verified official download, receipt reopening and refreshed readiness. On
  `2f08`, [native revalidation](../artifacts/provisioning/native-validation-2f08.json)
  showed the old runtime-bound receipt as “Not verified” and restored “Ready” only
  after explicit zero-download validation; the historical receipt remains readable.
- [The `2f08` native goal walkthrough](../artifacts/provisioning/native-agent-acceptance-2f08.json)
  produced five preview frames and 20 unreviewed annotation images with one Qwen
  call (88.817 seconds), then opened the exact preview image in the editor. The new
  box-edit check is incomplete because CUA ScreenCaptureKit returned an invalid-
  parameter error. Annotations and the original project's four checked files are
  unchanged; the QA project remains unreviewed. There is no accuracy, evaluation
  or deployment approval claim. [Canonical copy/install and signature verification passed](../artifacts/provisioning/package-installation-2f08.json);
  the prior bundle is preserved, and canonical relaunch UI has not been verified.

This is one reviewed model recipe, not a general installer. OWLv2 and RT-DETR
still need exact reviewed multi-artifact manifests before joining this API.
Dependency installation, automatic destructive repair, further YOLO variants,
PaddleOCR integration and SAM 3 hardware/adapter support remain outside this
slice. The isolated PaddleOCR probe remains separate from callable app support.

## Reader selection foundation in development

New planning-options version `0.3` writes the selected OCR model into the
candidate's `ocr.params.model`. Missing legacy parameters still mean
`apple-vision`; saved `0.1`/`0.2` choices reconstruct their original implicit Apple
graphs during effect-free replay. Barcode remains a separate Apple-only request.
The candidate, saved selection, compiled adapter identity and evaluation hash must
agree. Text/FPS/target refinements preserve that model choice; the task comparison
binds OCR language and keeps OCR separate from barcode while allowing different
OCR models to share one validation protocol.

The intended alternative ID `ppocr-v5-mobile-en` is accepted by the typed OCR
authoring contract, but **has no registered production adapter or callable
capability in this slice**. Compilation/common execution rejects it; it cannot
fall back to Apple Vision. New planner options require an installed, compatible
catalog entry and a resolvable coded adapter. Tests using a mocked future reader
identity establish only this selection/binding contract, not Paddle inference,
installation, accuracy or readiness. The independent reduced-runtime probe must
pass its runtime, output, artifact and license checks before integration is approved.
