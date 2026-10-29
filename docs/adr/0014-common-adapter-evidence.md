# ADR 0014: common evidence for existing inference adapters

Status: implemented for the existing fixture, OWLv2, RT-DETRv2, local RT-DETR/SSDLite and native Apple Vision adapters. This change installs no model, adds no dependency and exposes no new model choice.

## Compatible output addition

PipelineSpec remains version 0.1 with unchanged graph ports and parameters. FrameResult gains optional `inferences`, defaulting to an empty list for historical records. Each entry identifies its block and contains an InferenceResult version 1 plus an `input_to_frame` transform. Old detections, text, counts and events retain their behavior. Clients which decode only known fields continue to work; strict external consumers must adopt this additive response field before upgrading.

Observation boxes/polygons are normalized, top-left coordinates in the actual adapter input image. The transform `(offset_x, offset_y, scale_x, scale_y)` maps those observations into the original frame. Legacy FrameResult detections have already been mapped once. Consumers must not apply the transform to those legacy detections again. Reader evidence retains duplicate literal strings while the legacy `texts` projection retains its existing deduplication.

The current native bridge provides strings only. Its confidence, geometry and symbology remain null. No transliteration, expected-text correction or fabricated confidence is introduced. Component timings and model-cache state also remain null until instrumented; `total_ms` measures the facade call, including identity checks and input preparation, and is not claimed as pure model inference time.

## Evidence and caches

The compiler records the resolved adapter identity per block. Execution verifies that identity before and after a call, rejecting changed artifacts and discarding late or cancelled results. Unavailable Apple Vision can still be represented during authoring, but execution requires the configured bridge. No adapter is substituted automatically.

Model identities bind all local weight/config/tokenizer/vocabulary files consumed by the current adapters, implementation source, request parameters, provider, dependency-version manifest and system identity. Native evidence binds bridge content and the existing macOS/kernel/request-policy identity, without claiming access to Apple's hidden model weights. The synthetic fixture explicitly uses the `synthetic_code` identity scope. Runtime dependency metadata is version evidence, not a claim that all installed library bytes were independently attested.

After an adapter is first used, changing its implementation source requires an engine restart. An already-imported implementation cannot be relabeled with newly edited source bytes.

Learned-model caches are keyed by content fingerprints and paths, plus the effective MPS/CPU provider where applicable. File identity, ctime, mtime and size invalidate cached file digests; returned identities contain actual content SHA256 values. Same-size writes with restored modification times and atomic replacements invalidate the identity. Artifacts changing while being hashed or loaded fail closed. This is local lifecycle integrity, not protection against a privileged attacker modifying the process or kernel.

Evaluation hashes now bind these adapter identities, so previous evaluations require rerunning before approval. Dataset hashes, human review and deployment approval requirements remain unchanged. In-process Torch kernels cannot be interrupted reliably mid-call: cancellation/deadline checks before and after execution discard results. No promise of hard kernel cancellation is made.

## Deferred

YOLOX and Paddle remain isolated probes. Rich native text geometry needs a separately versioned bridge protocol; reader model selection requires coordinated compiler/executor/planner changes. Neither is part of this slice. Transitive dependency/license review remains required before new runtimes are distributed.
