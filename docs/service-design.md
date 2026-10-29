# Local service design

Owner: integration. `WorkspaceService(Path)` coordinates typed engine components.
FastAPI serves HTTP/1.1 exclusively on a user-owned Unix socket. The native app is
an API client; MCP wraps the same methods without access to approval endpoints.

Each project owns copied media, annotations, pipeline candidates, evaluation
records, deployment evidence, crops, and chat messages. JSON writes are atomic;
SQLite uses WAL and bound parameters. Candidate, zone, media or annotation edits
invalidate saved approval. Deployment checks a freshly calculated spec and dataset
hash against saved evaluation and requires a human API action. An override requires
a nonempty recorded reason and never substitutes for reviewing the eval set.

Long vision calls execute outside the event loop. Per-workspace service mutations
use a lock and compare saved state before attaching results. Model/network failures
produce typed boundary errors rather than success-looking fixture output. Questions
about evidence are answered through bounded, transparent filters, never arbitrary
SQL supplied by a model. Synthetic evidence remains tagged through export.

Tests: persisted restart, traversal rejection, independent project data, copied
input integrity, stale approval/evaluation rejection, explicit override, and a
complete synthetic walkthrough. The UI includes its own human approval step.
