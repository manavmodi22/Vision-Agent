# VisionApp implementation contract · 2026-10-28

Status: initial engineering implementation; acceptance is measured by tests and
visible workflows, not by completeness of the planning document.

## Ownership and dependency direction

* CV owner: `spec/`, `engine/{blocks,compiler,runtime,models,eval,train,llm_client}`
  and their tests. Pure typed spec, safe compiler, real vision adapters, honest
  synthetic fixtures, metrics. No imports from app, agent or API.
* Agent owner: `agent/`, `mcp_server/`, `evals/` and their tests. Explicit phase
  machine, typed local planner, genuine MCP client/server, bounded calls. No
  direct file/model access by the agent: tools are the boundary.
* Mac owner: `app/` and app tests. SwiftUI executable built with Swift Package
  Manager (macOS 15+), socket client, engine supervisor, Apple Vision bridge.
* Integration owner: `engine/api/`, `engine/store/`, `engine/service.py`, scripts,
  packaging, project persistence, API tests, integration and dependency manifests.

## Core Python interface (v0.1)

`spec.models` exports `PipelineSpec`, `TaskBrief`, `Detection`, `FrameResult`,
`RunResult`, `EvaluationResult`, `Annotation`, `EvalDataset`. Pydantic v2,
`extra=forbid`, JSON serializable, normalized bounding boxes `[x1,y1,x2,y2]`.

`PipelineSpec` follows the supplied graph shape: `spec_version`, `name`,
`inputs: {source: {type, path}}`, `blocks: [{id,type,params,in}]`, optional `eval`.
Block params are validated by their registered typed block schemas.

`engine.compiler.compile_pipeline(spec, project_root: Path) -> CompiledPipeline`.
`engine.runtime.run_pipeline(spec, project_root: Path, max_frames: int = 50) -> RunResult`.
`RunResult`: `frames: list[FrameResult]`, `elapsed_s`, `warnings: list[str]`.
`FrameResult`: `image_path`, `detections`, `counts: dict[str,int]`, `texts: list[str]`,
`events: list[dict[str,JsonValue]]`, `elapsed_ms`.
`Detection`: `label`, `confidence`, `box: list[float]`, optional `zone`.
`Annotation`: `image_path`, `detections`, `reviewed: bool = False`.
`EvalDataset`: `id`, `annotations: list[Annotation]`.
`engine.eval.evaluate(spec, dataset, project_root: Path) -> EvaluationResult`:
`precision`, `recall`, `count_mae`, `passed`, `metric`, `target`, `sample_count`,
`failures: list[dict[str,JsonValue]]`, `spec_hash`, `dataset_hash`.
`engine.models.list_models() -> list[dict[str,JsonValue]]`.
`engine.blocks.list_blocks() -> list[dict[str,JsonValue]]`.
Errors are explicit ValueError subclasses; unavailable models never become fixture
models. Fixtures are labelled synthetic and excluded from production claims.

## Agent interface

`agent.machine.AgentState`: typed serializable state, phase plus evidence/gates.
`agent.planner.plan(brief: str, source_path: str, settings: dict[str,JsonValue])`
`->` awaitable `PlanResult` with `message`, `questions: list[str]`,
`candidates: list[PipelineSpec]`. Real local model only; unavailability errors.
`agent.templates.build_template(use_case: str, source_path: str, model: str)`
`-> list[PipelineSpec]` is an explicitly user-selected deterministic template,
never presented as output from an LLM. Use cases `pallets`, `damage`, `labels`.

MCP exposes thin wrappers around `engine.service.WorkspaceService`.
If integration methods aren't ready, coordinate directly, do not duplicate storage.

## Local HTTP-over-Unix-socket contract

Socket: `VISION_SOCKET` or `/tmp/visionapp-<uid>/engine.sock` (parent 0700, socket
0600). No TCP listener. `VISION_DATA_DIR` defaults to application support.
App launches `.venv/bin/python -m engine.api --socket … --data-dir …` from repo.
Requests and responses use snake_case JSON; errors `{detail: string}`.

* GET `/health`: `{status,version,model_server:{reachable,models,error},capabilities}`.
* GET/POST `/projects`: response list/project; create `{name,use_case}`.
* GET `/projects/{id}`: project detail.
* POST `/projects/{id}/media`: `{paths:[absolutePath]}` copies and samples images/video.
* POST `/projects/{id}/demo`: installs synthetic fixture media and reviewed labels.
* POST `/projects/{id}/plan`: `{prompt,mode:"template"|"agent",model}`;
  response `{message,questions,candidates:[spec],project}`.
* POST `/projects/{id}/preview`: `{candidate_index:0}` -> RunResult.
* PUT `/projects/{id}/zones`: `{zones:[{id,polygon:[[x,y],…]}]}` updates specs.
* GET/PUT `/projects/{id}/annotations`: EvalDataset request and response.
* POST `/projects/{id}/evaluate`: `{candidate_index:0}` -> EvaluationResult.
* POST `/projects/{id}/deploy`: `{candidate_index:0,approved:true,override_reason:null}`
  -> `{deployment_id,status}`. Server enforces current spec+dataset hash evidence,
  explicit approval, reviewed labels, target OR recorded override.
* POST `/projects/{id}/run`: `{candidate_index:0,max_frames:50}` -> RunResult.
  Requires approved deployment, stores events/crops and hard frames.
* GET `/projects/{id}/events`: list of events `{id,created_at,image_path,crop_path,
  label,confidence,counts,payload}`; GET `.../events.csv` exports.
* GET `/projects/{id}/review`: list of review entries `{id,image_path,reason,status}`.
* POST `/projects/{id}/review/{review_id}`: `{status:"accepted"|"skipped"}`.
* POST `/projects/{id}/ask`: `{question}` -> `{answer,evidence:[events]}`.
* GET/PUT `/settings`: `{model_url,planner_model,vlm_model,allow_agpl}`.
* GET `/models`, GET `/blocks`.

Project: `{id,name,use_case,status,created_at,updated_at,media:[absolutePath],
brief,candidates:[spec],evaluations:[EvaluationResult],messages:[{role,content}],
synthetic:bool,deployment_id:null|string}`. Persist atomic project JSON plus SQLite
events; restart cannot manufacture approval or reuse stale evaluation evidence.

## Native vision bridge

The Swift executable supports `--analyze-image <path>` without opening a window.
Writes JSON `{texts:[string],barcodes:[string]}` to stdout via Apple Vision;
nonzero exit on failure. Python finds it via `VISION_APP_BINARY`.

## Initial acceptance and failure modes

Compiler tests cover unresolved references, cycles, incompatible ports, unsafe
expressions, unknown models and license checks. Evaluation tests cover IoU
matching, empty sets, unreviewed labels and stale evidence. Workflow tests cover
project restart, template -> preview -> evaluation -> explicit deploy -> run ->
evidence; offline models fail clearly. Swift build + native window inspection is
required. Heavy model training, camera/shared-memory capture, signing and real
warehouse accuracy must be reported separately if not verified.
