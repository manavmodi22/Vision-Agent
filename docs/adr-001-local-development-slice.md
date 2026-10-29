# ADR001: a verifiable local development slice

The supplied build plan remains the product reference, not a claim of completed
milestones. Its diagrams and detailed phase gates were not present as readable
content. This first implementation concentrates on a working, testable path.

Decisions:

- SwiftPM produces the native executable without full Xcode. The local development
  bundle records a checkout path and uses its virtual environment. A relocatable
  bundled interpreter and release notarization remain separate packaging work.
- `engine.api` is the composition root wiring planner, tools and service. This is
  an explicit exception to package-name layering; core runtime, compiler,
  evaluation and model modules never import the agent or call a planner.
- A local model chooses a small typed pattern/parameter decision. Authored patterns
  compile it into a PipelineSpec. Asking a small model for an unrestricted graph
  proved less reliable in live tests. The spec is still validated and previewed
  through real MCP before being presented.
- llama.cpp serves an existing local GGUF because LM Studio's daemon was
  unavailable. The compatible endpoint is replaceable in Settings.
- Original rectangle fixtures verify software behavior. NVIDIA synthetic and real
  frames verify distinct inference/evaluation paths. Data and label provenance
  remain separate; failed model scores never become deployment permission.
- Local SSDLite establishes optimization, versioning and promotion gates. It starts
  from scratch or continues a local checkpoint. Useful pretrained specialization
  and additional model families remain further model work.
- Project data, annotations and approval evidence persist. Interrupted jobs are
  identified after process loss. A cross-process lease prevents concurrent
  trainers and prevents recovery from misclassifying a live worker.
- External alert delivery, continuous capture and VLM judgement are explicitly
  unavailable capabilities. See status.md for remaining scope.

Validation is recorded in artifacts/ and tests. Benchmark scores are narrow
observations and must not be generalized to production accuracy.
