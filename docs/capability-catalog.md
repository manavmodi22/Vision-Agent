# Capability discovery foundation

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

Unsupported SAM 3, YOLO and OCR-alternative slots have no callable claim or
install action. Availability-to-install is reserved for implemented adapters
with a compatible existing manual-weight or bundled installation path. There is
no installation API in this foundation.

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
