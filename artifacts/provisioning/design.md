# Reviewed capability provisioning

The user selects a catalog model, reviews an immutable plan containing exact source URLs, artifact hashes/bytes, license declarations, fixed installation location, host prerequisites and limits, then explicitly approves that plan ID and hash. No endpoint accepts arbitrary URLs, paths, package names or commands. Registry changes, target changes or runtime changes require a new plan.

A durable background job streams only allowlisted pinned artifacts into a private staging directory, checks size and SHA256, then atomically renames a complete new installation into its fixed target. Existing differing files are preserved and block replacement. Restarts mark unfinished jobs interrupted; retry is a new explicit job. Repeated start requests return the same active job, and a completed result is reused only while its evidence is current.

Installation is distinct from readiness. A fixed subprocess runs one generated black-image inference with an enforced timeout, without project or user-image access. A passing receipt binds installed content and current runtime/host/dependency identity; it proves bounded execution only, never accuracy. A failed smoke leaves verified weights installed but not callable. Catalog discovery may read current receipts, and never invokes inference itself.

Initial supported installation is the official pinned YOLOX-s ONNX release and its pinned Apache-2.0 repository license. No weights are packaged or redistributed. OWLv2/RT-DETR are not added to this installer without an exact reviewed per-artifact manifest; existing installation methods remain available.
