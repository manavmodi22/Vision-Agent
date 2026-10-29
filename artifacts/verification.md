# Verified development build — 2026-10-28

Reference machine: Apple M4 Pro, 48 GB RAM.

| Check | Observed result |
|---|---|
| Python behavioral suite | 216 tests passed in 83.30 s, including interrupted training recovery |
| Strict typing | mypy clean across 103 files in spec, engine, agent, MCP and evals |
| Lint | Ruff clean |
| Native build | SwiftPM debug and release built |
| Native executable checks | 67 passed in the packaged executable |
| Native OCR | Apple Vision recognized PALLET 12345 and DOCK 4 |
| App signature | codesign --verify --deep --strict passed, local ad-hoc signature |
| Engine transport | Unix socket; directory 0700, socket 0600; no engine TCP listener; health check returned ok |
| Packaged app | Opened, connected to supervised engine and local planner |
| Describe-to-app journey | Native Home goal + NVIDIA sample automatically imported 20 real frames, compiled a candidate, produced an actual 5-frame OWLv2 preview and saved unverified proposals on 20 images |
| Conversational refinement | “Lower confidence to 0.15” changed only min_conf from 0.4 to 0.15, preserved all other graph fields, and reran the preview; detections changed from 2 to 7 across 5 images |
| Contextual review | Agent opened the editable annotation canvas. Continue without human review remained awaiting_review, with zero evaluations and no deployment |
| Candidate orchestration | Fixture acceptance tests exercise every candidate, correct metric direction, common holdout/goal scope, winning-candidate preview and the explicit deployment gate; added classes require fresh human review |
| Native annotations | Drew, moved and resized a person box; zoom, undo/redo, autosave and reopen verified on real NVIDIA warehouse imagery |
| Custom dataset | Added a pallet class; 12-image workspace retains manual labels separately from model predictions; all images remain unreviewed |
| Workflow editing | Changed confidence to 0.18; added and reordered resize; connected its image output; validated, saved and reopened the pipeline |
| Real image workflow | Edited pipeline preview processed 5 OWLv2 frames in 10.60 s, including model loading; this is not steady-state camera FPS |
| Preview honesty | Unrun samples are labeled as input; zone geometry is drawn only when used by the selected workflow |
| Dataset contracts | COCO round trip and normalized-file import, immutable portable snapshots, conflicting-save rejection and holdout isolation covered by tests |
| Label gate | Unreviewed real images rejected for evaluation |
| Live planner | Custom person/forklift request produced a compiled pipeline and actual 5-frame OWLv2 preview; durable commit, reload, 6 trace spans and effect-free replay verified |
| Conversation | Missing lane capacity asked; answer 7 retained and compiled threshold 7 |
| Local VLM | Actual Cosmos crop judgement and compiled VLM pipeline ran; judgement remains a model hypothesis |
| Pretrained training | RT-DETRv2 R18 trained on MPS for 10 epochs / 50 steps in 60.82 s, then reloaded for held-out scoring |
| Training result | 10 disjoint but correlated synthetic held-out frames: precision 0.6168, recall 0.7732, count MAE 14.2; recall target 0.80 FAILED; no promotion |
| Background job | Reviewed training subset and disjoint holdout enforced; unreviewed pool preserved; no automatic deployment |
| New-media execution | Tests verify approved workflows run on separate input copies without changing the development dataset or approval; stale approval rejected |
| Alerts | Loopback HTTP retry/idempotency, SMTP and MQTT QoS 1 protocol checks passed; no external destination configured or contacted |
| Earlier NVIDIA baseline | 30 synthetic frames; precision 0.8591 / recall 0.3918; target 0.80 FAILED |
| Native video ingress | Actual AVAssetReader replay through shared memory and OWLv2: 11 frames in the bounded probe, correct orientation; preview retained no events |
| Semantic evidence | Actual local-model probes passed 5 of 6; one valid time-window phrase unnecessarily requested clarification. No incorrect count was accepted |
| Recovery | Interrupted training rechecks current candidates; it cannot reuse the consumed training approval or automatically repeat an uncertain recorded run |
| Bundle identity | Final packaged Python source matches the checkout; fingerprint retained in agent-experience/final-source-identity.json |
| Relocation | Final bundle moved to a path with spaces: isolated bundled imports, real OWLv2 inference, Apple Vision, semantic question with exact count 13, 67 native checks and post-execution signature verification all passed |

These checks demonstrate development workflows. They do not establish production
readiness, unique-object counting, pallet/damage/barcode accuracy, or steady-state
camera FPS. The full scope gaps are recorded in docs/status.md. The default app
bundles its Python runtime and dependencies. It is locally ad-hoc signed, not
notarized. Camera/screen hardware permission flows remain unverified.

Evidence: [native authoring UI](native-authoring-ui.json),
[agent-first native acceptance](agent-experience/acceptance.json),
[relocated package](bundle-verification.json),
[durable custom agent](custom-agent-durable-live.json),
[pretrained specialization](vision-verification/rtdetr-pretrained-specialization.json),
[VLM pipeline](vision-verification/cosmos-pipeline-run.json),
[implementation status](../docs/status.md). Earlier probes remain in
planner-complete-brief.json, planner-probes.json, pattern-benchmark.json and
nvidia-benchmark/.

Final checks: `ruff check .`, `mypy spec engine agent mcp_server evals`, `pytest -q`,
packaged `VisionApp --self-test`, `codesign --verify --deep --strict`, and the
running engine's Unix-socket `/health` endpoint.
