# Native app interface and verification

Owner: native_app. SwiftUI macOS 15 executable, built by Swift Package Manager.

`EngineClient.request` uses HTTP/1.1 over the private Unix socket; no TCP port is
opened. A fresh socket per request bounds lifecycle and supports content length
and chunked bodies. A 240 second receive timeout leaves headroom beyond the bounded 185 second
planner request while preventing hung local jobs from blocking indefinitely. UI work remains on the main actor; socket work is detached.

`EngineSupervisor` launches only the configured repo interpreter/module, sets the
native executable path for the Apple Vision bridge, captures logs, restarts at
most three times, and terminates only its own child on app exit. It connects to an
already running engine without taking ownership. Health and model availability
are separate. Errors remain visible; there is no substitute inference.

`WorkspaceModel` is the main-actor state holder for persisted project data, current
preview, annotations, evaluation and events. Every UI approval is an explicit
request; the server remains authoritative for stale evidence and deployment gates.

`--analyze-image path` executes Apple Vision OCR and barcode recognition before
SwiftUI starts, emitting a small JSON result. It needs no camera permissions.

The native app includes project creation, synthetic walkthrough, local files,
planner/template selection, graph, overlays, drawn zones, reviewed box labels,
evaluation, deployment approval, runs, evidence, review and model settings.
Training uses a separately approved, bounded background job and polls status
without blocking the rest of the workspace. Camera/shared-memory acquisition and
notarized distribution are separate work;
UI must not imply they are operational here.

Validation: Swift build passed. Eight executable native self-tests passed for
HTTP body parsing, incomplete response rejection, coordinate transforms and wire
keys. XCTest is present but unavailable on the initial CommandLineTools-only Mac.
Apple Vision CLI recognized both fixture text lines. The native window, a real
OWLv2 preview on five warehouse images, and rejection of evaluation on unreviewed
labels were visually verified through the native UI.
