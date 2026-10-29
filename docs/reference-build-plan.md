# Vision-App Agent for Mac — Build Plan & Architecture

> **Architecture update (2026-10-28):** The current build implements only part of
> this original plan. Use [agent platform revision](agent-platform-revision.md)
> for the updated orchestrator, separate planning/execution, capability catalog,
> model adapters, Markdown skills, web-source acquisition and evaluation gates.
> Model families listed below are proposals unless `docs/blocks.md` and the model
> registry confirm they are executable.

Oct 28, 2026 · @Manav Modi

## Purpose

We will build a native Mac app where a warehouse user describes a vision task in plain English and gets a tested, running vision pipeline back — the Roboflow Agent idea, built entirely by us on open-source parts, running locally. This doc is the how: architecture, agent design, models, app design, code structure, standards and milestones. The research and scoping lives in the companion doc, [Promptable Vision-App Agent — Research & Scope](https://claude.ai/artifact/HA2gWYhGgirS3NpgG1HxkL).

**Ground rules for the build**

- Everything is ours: agent loop, tools, vision engine, eval, training, app. Open-source libraries only.
- **LM Studio serves models and nothing else.** It runs the planner LLM and the vision-language model behind an OpenAI-compatible API on localhost; we can swap it for Ollama, llama.cpp server or MLX-LM server without touching our code.
- No Roboflow software, and no LM Studio Bionic.
- The agent produces a **validated pipeline spec, not free-form code** — the core idea we keep from Roboflow.
- Design before code: every module has a written interface, tests and an owner before it is built.

## Product: what the MVP must do end to end

The MVP is done when one person can run these five flows on a single Mac without touching code.

1. **Describe** — the user types a goal ("count pallets in lanes A–D and alert me when a lane is full") and drops in 20–50 sample images or a recorded clip. The agent asks at most 3 clarifying questions (zones, thresholds, what counts as "full").
2. **Build** — the agent proposes 1–3 candidate pipelines, compiles each into a spec, and shows the graph and a preview with boxes drawn on the samples.
3. **Prove** — the user confirms or fixes labels on a small eval set (10–50 images); the agent scores every candidate and shows precision, recall, count error and the worst failures. Nothing deploys below the target metric unless the user overrides it.
4. **Run** — the chosen pipeline runs on a folder, a video file or a camera; events with image crops land in the local store; alerts fire by webhook, email or MQTT.
5. **Improve and ask** — hard or low-confidence frames go to a review queue; one click fine-tunes a detector locally. The user asks questions in chat ("how many damaged pallets on dock 4 today?") and gets answers with evidence crops.

The three MVP use cases from the scope doc drive testing: **pallet count per lane**, **damaged carton or pallet**, and **label / barcode check**.

## System architecture

The system is two processes we write — a Swift app and a Python engine — plus LM Studio underneath as a replaceable model server.

&#91;embedded content: system architecture · 2 processes, 1 model server\]

Read it top down: the Swift app handles the window, cameras, screen capture and Apple Vision; the engine runs the agent, which reaches the vision code only through the MCP server (highlighted). Pipelines write events, alerts and hard frames; the agent and the VLM-judge block are the only callers of LM Studio.

| Layer | Owns | Never does |
| --- | --- | --- |
| Mac app (Swift) | UI, device access, permissions, engine supervision | Model inference beyond Apple Vision |
| Agent harness | Conversation, state, plans, approvals | Touch files, models or frames directly |
| MCP server | Tool contracts and input validation | Business logic |
| Vision engine | Compile, run, evaluate, train, store | Call the planner LLM |
| LM Studio | Serve LLM and VLM | Anything else |

## Agent design

The agent is a small, explicit state machine written by us, with Pydantic AI handling each LLM step: typed tool calls, typed outputs, retries on validation failure. The state machine — not the LLM — decides what phase we are in, so a weak local model cannot skip the eval gate or deploy by accident.

**States and what each one may do**

| State | Goal | Tools allowed | Exits when |
| --- | --- | --- | --- |
| Clarify | Turn the brief into a typed `TaskBrief` (objects, zones, metric, threshold, output) | `media_import`, `frames_sample`, `vlm_ask` | Brief validates and the user confirms it |
| Plan | Pick 1–3 pipeline patterns from the skills library | `blocks_list`, `block_schema`, `detect_open_vocab` (probe) | Each candidate has a pattern and a model choice |
| Compile | Write each candidate as a `PipelineSpec` | `pipeline_validate`, `pipeline_run` (on 5 samples) | Spec passes schema + type checks and runs |
| Evaluate | Score candidates on the eval set | `eval_create`, `eval_run`, `review_queue` | Best candidate hits target, or user overrides |
| Specialize | Fine-tune when zero-shot misses target or is too slow | `train_start`, `train_status`, `eval_run` | New model beats the old one on the same eval set |
| Deploy | Run the chosen spec | `pipeline_deploy`, `alerts_set` | User approves (always a human step) |
| Operate | Answer questions, report, collect hard frames | `events_query`, `report_make`, `review_queue` | Ongoing |

**How the parts fit**

- **Model client** — Pydantic AI's OpenAI-compatible model pointed at `http://localhost:1234/v1` (LM Studio's default port). One config file names the planner model and the VLM; nothing else in the code knows about LM Studio.
- **Tools** — every tool lives in our MCP server with a Pydantic input and output model. The agent connects as an MCP client, so the same tools work from Claude Code or Cursor for debugging.
- **Skills** — Markdown playbooks (pallets, damage, labels, docks; model choice per Mac; reading eval results). The state machine loads only the skills relevant to the current state and task, to keep the local model's context small.
- **Memory** — each project is a folder: brief, specs, eval sets, run history, chat log. The agent reads project state from disk, not from its context window, so it can resume after a crash or restart.
- **Long jobs** — training and batch eval run as background jobs in the engine; the agent polls `train_status` and the app shows progress.
- **Tracing** — every LLM call and tool call is logged with OpenTelemetry to a local trace viewer (Arize Phoenix or Langfuse, both self-hostable), so a bad run can be replayed.

**Guardrails**

- Output is always a `PipelineSpec` or a typed answer — never code the app executes.
- Constrained JSON decoding for tool arguments where LM Studio supports structured output; up to 2 automatic retries, then the agent explains the failure to the user.
- Deploy, alert changes and deleting data always need a user click.
- Budgets per run: max tool calls, max wall-clock time, max training minutes.

**Computer use**

The app gets two Mac-native abilities beyond files and cameras, both behind explicit macOS permissions:

- **Screen as a video source** (MVP-adjacent) — capture a window or region with ScreenCaptureKit, so the agent can watch a camera vendor's viewer or an NVR app that has no API, and run a pipeline on it like any other source.
- **Acting on other apps** (after MVP) — a `computer` tool that takes screenshots and clicks or types through the Accessibility API, for example to open an NVR export dialog or enter a result into a WMS screen. Every action is shown first and needs approval until the user trusts a specific routine.

The local planner model will be weaker than frontier models at computer use, so it stays out of the critical path for the MVP.

## Pipeline spec and block library

A pipeline is a versioned JSON document: a directed graph of typed blocks. It is the contract between agent and engine, so it is designed first and changed only through a schema version bump.

```json
{
  "spec_version": "0.1",
  "name": "pallets-per-lane",
  "inputs": { "source": { "type": "video_file", "path": "clips/aisle3.mp4" } },
  "blocks": [
    { "id": "sample", "type": "frame_sample", "params": { "fps": 2 }, "in": { "frames": "$inputs.source" } },
    { "id": "det", "type": "detect", "params": { "model": "dfine-s-pallet-v3", "classes": ["pallet"], "min_conf": 0.4 }, "in": { "image": "$sample.frame" } },
    { "id": "zones", "type": "zone_filter", "params": { "zones": "zones/lanes.json" }, "in": { "dets": "$det.dets" } },
    { "id": "count", "type": "count_per_zone", "in": { "dets": "$zones.dets" } },
    { "id": "full", "type": "rule", "params": { "when": "count >= 12", "hold_s": 30 }, "in": { "value": "$count.counts" } },
    { "id": "out", "type": "sink_event", "params": { "alert": "webhook:ops" }, "in": { "event": "$full.event" } }
  ],
  "eval": { "set": "eval/lanes-v1", "metric": "count_mae", "target": 0.5 }
}
```

**Rules the compiler enforces:** every input reference resolves; port types match (image, detections, tracks, counts, text, event); the graph has no cycles; models exist locally and their licence is allowed; estimated FPS on this Mac is shown before run. Rule expressions use a tiny safe expression language, never Python `eval`.

**Block library (MVP)**

| Group | Blocks |
| --- | --- |
| Sources | `image_folder`, `video_file`, `camera` (USB/RTSP later), `screen_capture` |
| Frames | `frame_sample`, `crop`, `resize`, `tile` (for small objects in wide shots) |
| Detection | `detect` (trained model), `detect_open_vocab` (text prompt), `segment` (optional) |
| Reading | `ocr` (Apple Vision), `barcode` (Apple Vision), `classify` |
| Judgement | `vlm_judge` (crop + question → label + reason via LM Studio) |
| Space and time | `track`, `zone_filter`, `line_cross`, `count_per_zone`, `dwell` |
| Logic | `rule`, `match` (e.g. OCR text vs. expected SKU), `debounce` |
| Outputs | `sink_event`, `sink_alert`, `sink_dataset` (save frames for review) |

Each block is one Python class with typed `Params`, `Inputs` and `Outputs` models, a `run()` method, a unit test with fixture images, and a short doc string the agent reads through `block_schema`.

## Model lineup

We support the YOLO family from day one because it is the fastest way to good results on a Mac, and keep Apache-licensed detectors alongside it so a commercial product is never blocked. The model manager tags every model with its licence and the app shows it.

**Licence decision:** Ultralytics YOLO (YOLO11, YOLO26) is AGPL-3.0. That is fine while we are an open-source proof of concept, but [a product that ships it must publish its source or buy a commercial licence](https://pypi.org/project/easydetect/). D-FINE, DEIM and RT-DETRv2 are [Apache-2.0, code and weights](https://playground.roboflow.com/models/compare/d-fine-vs-yolo26), so they are the default for anything we might sell.

| Role | Models | Licence | How it runs on the Mac | MVP? |
| --- | --- | --- | --- | --- |
| Fast trainable detector | Ultralytics YOLO11 / YOLO26 (n–x), detect, segment, pose, OBB | AGPL-3.0 | Train on MPS; built-in Core ML export | Yes |
| Permissive trainable detector | D-FINE, DEIM / DEIMv2, RT-DETRv2 | Apache-2.0 | Fine-tune on MPS; Core ML export via coremltools | Yes (default for commercial) |
| Permissive lightweight YOLO | YOLOX | Apache-2.0 | Core ML export | Optional |
| Open-vocabulary detection | OWLv2, Grounding DINO, Florence-2; YOLO-World / YOLOE | Apache / MIT; AGPL for Ultralytics versions | PyTorch MPS | Yes — first pass + auto-labeling |
| Segmentation | SAM 2 | Apache-2.0 | PyTorch MPS | Optional (cleaner labels) |
| OCR + barcodes | Apple Vision framework | macOS built-in | Neural Engine, no model to ship | Yes |
| Tracking | ByteTrack, OC-SORT | MIT | CPU | Yes |
| Vision-language judge | Qwen-VL family, Gemma family (vision) | Per model card | Served by LM Studio | Yes |
| Planner LLM | 2–3 candidates with good tool calling (e.g. Qwen, Gemma, gpt-oss) | Per model card | Served by LM Studio | Yes — chosen by week-1 benchmark |

Not used: RF-DETR and other Roboflow models (our no-Roboflow rule), and YOLO-NAS, whose [weights are non-commercial](https://playground.roboflow.com/models/compare/d-fine-vs-yolo-nas).

**How models are chosen at build time:** start zero-shot (open-vocab detector, or VLM judge on crops); if eval misses the target or FPS is too low, auto-label the samples with the open-vocab model, have the user fix a few, then fine-tune YOLO or D-FINE and export to Core ML. The agent's skills hold the rules of thumb (small objects → tiling; many similar objects → trained detector; subjective judgement like "damaged" → VLM).

## Mac app design

The app is a SwiftUI shell over a Python engine that runs as a local background process. Swift owns the window, cameras, screen capture and Apple Vision; Python owns models, pipelines, the agent and training. They talk over a local API on a Unix socket, never a public port.

**Screens**

| Screen | What the user does there |
| --- | --- |
| Projects | Create a project per use case; see status (building, evaluating, running) and last alert |
| Build | Chat with the agent on the left; on the right, sample images with live boxes and the pipeline graph |
| Zones | Draw lanes, dock doors or regions on a reference frame; saved as JSON the spec points to |
| Evaluate | Eval set grid, candidate scorecards side by side, worst failures first, fix-a-label in place |
| Run | Live view with overlays per source, FPS, current counts |
| Events | Timeline with crops, filters, export CSV |
| Review | Queue of hard frames: accept, fix, skip; "retrain" button with progress |
| Settings | LM Studio URL and models, permissions (camera, screen), alert targets, model licences |

**Process model**

- `VisionApp` (Swift) starts and supervises `vision-engine` (Python, bundled with its own interpreter), restarts it on crash, and shows its logs.
- Frames from cameras and screen capture are captured in Swift (AVFoundation, ScreenCaptureKit) and passed to the engine through shared memory, not encoded over the socket.
- The app checks that LM Studio is reachable and the configured models are loaded, and tells the user exactly what to load if not.

**Packaging**

- Signed, notarized `.app` with a hardened runtime; Python and wheels bundled; models downloaded on first use into `~/Library/Application Support/VisionApp/models`.
- Minimum target: Apple silicon, macOS 15, 32 GB RAM recommended (planner LLM + VLM + detectors share unified memory). Reference machine to be fixed in week 1.

## Repo structure and module boundaries

One monorepo, one direction of dependencies: `app` → `agent` → `mcp_server` → `engine` → `spec`. Lower layers never import higher ones, and `engine` never imports anything about LLMs except the VLM client.

```text
vision-agent/
├── spec/                 # pipeline JSON schema, Pydantic models, versioning — no other deps
├── engine/
│   ├── blocks/           # one module per block group (sources, detection, reading, logic, sinks)
│   ├── compiler/         # spec → executable graph; type checks; FPS estimate
│   ├── runtime/          # graph executor, frame scheduler, tracking state
│   ├── models/           # model manager, licences, backends (ultralytics, dfine, owlv2, coreml)
│   ├── eval/             # datasets, metrics, candidate comparison
│   ├── train/            # auto-label, fine-tune jobs, Core ML export
│   ├── store/            # SQLite events, crops, DuckDB queries
│   └── llm_client/       # OpenAI-compatible client for the VLM (LM Studio)
├── mcp_server/           # tool definitions only: thin wrappers over engine APIs
├── agent/
│   ├── states/           # one module per state; transitions in machine.py
│   ├── prompts/          # system prompts, versioned
│   └── skills/           # warehouse playbooks (Markdown)
├── app/                  # Xcode project: SwiftUI, capture, Apple Vision bridge, engine supervisor
├── evals/                # agent benchmark: 20+ warehouse briefs with expected outcomes
├── fixtures/             # small test images and clips (checked in), large data via git LFS
└── docs/                 # ADRs (architecture decision records), block reference
```

**Tooling:** Python 3.12 with `uv`, `ruff`, `mypy --strict` (or `pyright`), `pytest`; Swift with SwiftLint and XCTest; GitHub Actions on a self-hosted Apple silicon runner for model tests.

## Engineering standards

AI coding tools are welcome; unreviewed AI code is not. These rules apply to every pull request, whoever or whatever wrote it.

**Design first**

- Every module starts with an ADR or a one-page design note: purpose, public interface (typed signatures), data it owns, failure modes, how it is tested. Reviewed before code.
- Interfaces are Pydantic models or Swift protocols, written before implementations.
- The spec schema, MCP tool signatures and block interfaces are frozen per milestone; changes need an ADR.

**Code**

- Small, single-purpose functions; no file over \~400 lines; no dead code, commented-out code or TODOs without an issue link.
- Strict typing everywhere; no `Any` in public interfaces.
- Errors are typed and handled at boundaries; no bare `except`, no silent fallbacks that hide a failed model load.
- No new dependency without a short note: why, licence, maintenance status.
- Names say what things are (`count_per_zone`, not `process_data`).

**Tests and evaluation**

- Unit tests for every block with fixture images; golden-output tests for the compiler.
- The agent benchmark (`evals/`) runs on every agent or prompt change: 20+ warehouse briefs, scored on spec validity, eval metric reached, tool calls used and time taken. A change that lowers the score does not merge.
- Model tests run on the Apple silicon runner: accuracy on fixture sets and FPS, with thresholds.

**Review**

- Every PR has one human reviewer who can explain every line; the author states which parts were AI-generated.
- PRs stay under \~400 changed lines; bigger work is split.
- Definition of done: design note updated, tests pass, benchmark not worse, docs for any new block or tool.

## Milestones, exit criteria and team

The MVP takes about 13 weeks with 3 engineers; each milestone ends at a gate we must pass before starting the next.

&#91;embedded content: milestones · 5 phases, each with an exit gate\]

M2 is the real test of the idea: if the agent cannot turn plain-English briefs into working specs, we fix that before building more app. Durations are estimates to revisit after M0.

**Team:** one CV/ML engineer (models, eval, training), one agent/backend engineer (spec, compiler, MCP server, agent), one Swift engineer (app, capture, Apple Vision) joining from M1.

**After the MVP:** live RTSP cameras at scale, dock-door and aisle-obstruction packs, acting on other apps through computer use, WMS hooks, Windows/Linux.

## Decisions to make and risks

**Decisions needed before week 2**

- [ ] Reference Mac (chip and RAM) the team develops and benchmarks on.
- [ ] Planner model and VLM, picked from the week-1 benchmark.
- [ ] Is the repo open source from day one? If yes, AGPL YOLO is fine; if not, D-FINE/DEIM is the default detector.
- [ ] Source of the first 50–100 real warehouse frames and clips (partner DC, public datasets, staged shots).

**Top risks**

| Risk | Mitigation |
| --- | --- |
| Local planner model handles long tool loops poorly | State machine owns the flow; few typed tools per state; constrained JSON; benchmark gates every change |
| Memory contention on the Mac (LLM + VLM + detectors) | Memory budget in the model manager; unload models between phases; Core ML detectors |
| Pipelines look right but are wrong | Mandatory eval gate and failure gallery before deploy |
| Warehouse imagery is hard (glare, blur, shrink-wrap, occlusion) | Real DC frames in fixtures from week 1; tiling and trained detectors |
| Scope creep into a general CV platform | Three use cases only until M4 exit criteria are met |
| Licence mistakes | Licence tag per model, enforced by the compiler |

## Sources

- [Promptable Vision-App Agent — Research & Scope](https://claude.ai/artifact/HA2gWYhGgirS3NpgG1HxkL) (companion doc)
- [easydetect on PyPI — D-FINE packaging, licence comparison with Ultralytics YOLO](https://pypi.org/project/easydetect/)
- [D-FINE vs YOLO26 — licences and sizes](https://playground.roboflow.com/models/compare/d-fine-vs-yolo26)
- [D-FINE vs YOLO-NAS — YOLO-NAS weight licence](https://playground.roboflow.com/models/compare/d-fine-vs-yolo-nas)
- [DEIM vs YOLO26 — DEIM and DEIMv2](https://playground.roboflow.com/models/compare/deim-vs-yolo26)
