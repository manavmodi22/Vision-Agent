import Foundation

enum PlatformContractChecks {
    /// Optional server-produced payloads allow cross-language checks without inference or UI.
    static func checkFiles(_ arguments: [String]) throws -> Int {
        var checks = 0
        for (flag, path) in zip(arguments, arguments.dropFirst()) {
            switch flag {
            case "--reading-frame":
                _ = try JSONDecoder().decode(FrameResult.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--native-readings-v2":
                _ = try JSONDecoder().decode(NativeReadingsV2.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--capability-catalog":
                _ = try JSONDecoder().decode(CapabilityCatalog.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--build-status":
                _ = try JSONDecoder().decode(AgentBuildStatus.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--evaluation-configuration":
                _ = try JSONDecoder().decode(EvaluationConfiguration.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--evaluation-readiness":
                _ = try JSONDecoder().decode(EvaluationReadiness.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--evaluation-result":
                _ = try JSONDecoder().decode(Evaluation.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--provisioning-options":
                _ = try JSONDecoder().decode(ProvisioningOptions.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--provisioning-plan":
                _ = try JSONDecoder().decode(ProvisioningPlan.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--provisioning-job":
                _ = try JSONDecoder().decode(ProvisioningJob.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--provisioning-health":
                _ = try JSONDecoder().decode(ProvisioningHealth.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--build-artifact":
                _ = try JSONDecoder().decode(PlatformArtifactContent.self, from: Data(contentsOf: URL(fileURLWithPath: path))); checks += 1
            case "--planning-probe":
                let probe = try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
                _ = try JSONDecoder().decode(PlatformBuildPlan.self, from: JSONEncoder().encode(probe.object["plan"] ?? .null)); checks += 1
            default: break
            }
        }
        return checks
    }
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Platform check failed: " + message) }; checks += 1
        }
        let catalogWire = Data("""
        {"schema_version":"0.1","generated_at":"2026-10-28T15:00:00Z","host":{"memory_gib":48},"capabilities":[{"id":"model.example","name":"Example detector","kind":"model","description":"Local adapter","availability":"installed","implemented":true,"installation_ready":true,"callable":false,"task_types":["detection"],"version":null,"license":{"identifier":"Apache-2.0","code":null,"weights":null,"status":"declared","notes":[]},"provenance":{"source_urls":["https://example.org/model"],"revision":null,"hashes":{},"scope":"local_manifest","notes":[]},"hardware":{"platforms":["macOS"],"accelerators":["mps"],"required_packages":[],"minimum_memory_gib":null,"estimated_disk_bytes":null,"notes":[]},"side_effects":["local_inference"],"dependencies":[],"input_schema":{"type":"object"},"output_schema":{},"install_method":"manual_weights","install_instructions":null,"readiness":{"state":"unchecked","reason":"Weights found; inference has not been verified.","checked_at":"2026-10-28T15:00:00Z","evidence_scope":"metadata","evidence":[{"kind":"file","subject":"weights","outcome":"pass","detail":"Manifest exists","observed_at":"2026-10-28T15:00:00Z","metadata":{"bytes":123}}]}}]}
        """.utf8)
        let catalog = try JSONDecoder().decode(CapabilityCatalog.self, from: catalogWire)
        let installed = catalog.capabilities[0]
        try require(installed.availability == "installed" && !installed.verifiedCallable, "installed weights do not imply inference readiness")
        try require(installed.eligibleForValidation && installed.validationEligibilityMessage == "Eligible for a bounded validation; not yet verified.", "installed eligible unchecked adapter may run bounded validation without a health receipt")
        try require(installed.hardware.minimumMemoryGiB == nil && installed.readiness.evidence[0].metadata["bytes"] == .number(123), "nullable requirements and actual evidence remain distinct")
        var capabilityWire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(installed)).object
        capabilityWire["callable"] = .bool(true)
        var readiness = capabilityWire["readiness"]!.object; readiness["state"] = .string("ready"); capabilityWire["readiness"] = .object(readiness)
        let ready = try JSONDecoder().decode(Capability.self, from: JSONEncoder().encode(capabilityWire))
        try require(ready.verifiedCallable, "ready compatible installed capability is callable")
        capabilityWire["availability"] = .string("unsupported")
        let unsupported = try JSONDecoder().decode(Capability.self, from: JSONEncoder().encode(capabilityWire))
        try require(!unsupported.verifiedCallable, "unsupported capability cannot become callable through a stale ready flag")
        try require(!unsupported.eligibleForValidation && unsupported.validationEligibilityMessage == "Not eligible for bounded validation in its current state.", "unsupported capability cannot gain experiment eligibility through stale flags")
        capabilityWire["availability"] = .string("installed"); capabilityWire["installation_ready"] = .bool(false)
        let blocked = try JSONDecoder().decode(Capability.self, from: JSONEncoder().encode(capabilityWire))
        try require(!blocked.eligibleForValidation && !blocked.verifiedCallable && ready.validationEligibilityMessage == nil, "missing prerequisites block validation while verified ready capabilities need no unverified warning")
        try require(installed.matches("DETECTION") && !installed.matches("segmentation"), "catalog search uses actual declared task types")

        let planWire = Data("""
        {"id":"plan1","project_id":"project1","build_id":null,"operation_id":"operation1","revision":2,"parent_plan_id":"plan0","created_at":"2026-10-28T15:00:00Z","content_hash":"sha-plan","goal":"Count people","assumptions":["Fixed camera"],"candidates":[{"spec_version":"0.1","name":"Count","inputs":{"source":{"type":"image_folder","path":"media"}},"blocks":[],"eval":{"metric":"count_mae","target":0.5,"set":"eval"}}],"required_capabilities":["model.example"],"experiments":[{"id":"preview","phase":"preview","description":"Preview candidate","allowed_tools":["preview_pipeline"],"candidate_indices":[0]}],"metrics":[{"candidate_index":0,"metric":"count_mae","target":0.5,"direction":"minimize"}],"stop_conditions":["Stop on runtime error"],"human_checkpoints":[{"id":"labels","phase":"review","description":"Review labels","requires_approval":true}],"snapshot":{"workspace_hash":"work","dataset_hash":"data","model_hashes":["weights"],"settings_hash":"settings"},"skills":[{"id":"detection","version":"1.0","sha256":"skillhash"}],"revision_reason":"Changed goal"}
        """.utf8)
        let plan = try JSONDecoder().decode(PlatformBuildPlan.self, from: planWire)
        try require(plan.revision == 2 && plan.parentPlanID == "plan0" && plan.contentHash == "sha-plan", "plan revision provenance is preserved")
        try require(plan.metrics[0].targetLabel == "≤ 0.5" && plan.humanCheckpoints[0].requiresApproval, "measurement direction and real human gates survive decoding")
        try require(plan.skills[0].sha256 == "skillhash" && plan.requiredCapabilities == ["model.example"], "plan pins skills and actual capability requirements")
        try require(plan.modelSelections == nil && plan.modelSelections(for: 0).isEmpty && plan.planningOptionsArtifactID == nil, "historical plans decode without invented model reasons or option artifacts")
        var proposedWire = try JSONDecoder().decode(JSONValue.self, from: planWire).object
        if case .array(let candidates) = proposedWire["candidates"], let first = candidates.first { proposedWire["candidates"] = .array([first, first]) }
        proposedWire["model_selections"] = .array([
            .object(["candidate_index": .number(0), "capability_id": .string("model.owlv2"), "model_id": .string("owlv2-base-patch16"), "adapter_id": .string("owlv2"), "proposed_reason": .string("Test prompt-defined classes"), "options_snapshot_id": .string("options-snapshot"), "status": .string("proposed")]),
            .object(["candidate_index": .number(1), "capability_id": .string("model.local-detector"), "model_id": .string("local-detector"), "adapter_id": .string("rtdetr"), "proposed_reason": .string("Test the installed specialized candidate"), "options_snapshot_id": .string("options-snapshot"), "status": .string("proposed")])])
        proposedWire["planning_options_artifact_id"] = .string("opaque-options-artifact")
        let proposed = try JSONDecoder().decode(PlatformBuildPlan.self, from: JSONEncoder().encode(proposedWire))
        try require(proposed.modelSelections(for: 0).first?.modelID == "owlv2-base-patch16" && proposed.modelSelections(for: 1).first?.modelID == "local-detector" && proposed.modelSelections(for: 2).isEmpty, "per-candidate model proposals never leak onto another candidate")
        try require(proposed.modelSelections(for: 1).first?.proposedReason == "Test the installed specialized candidate" && proposed.modelSelections(for: 1).first?.status == "proposed", "model rationale remains the recorded proposal rather than measured evidence")
        try require(proposed.planningOptionsArtifactID == "opaque-options-artifact" && proposed.modelSelections(for: 0).first?.optionsSnapshotID == "options-snapshot", "model choice retains separate opaque artifact and options snapshot identities")
        let execution = try JSONDecoder().decode(PlatformExecution.self, from: Data("""
        {"id":"run","project_id":"project1","build_id":null,"operation_id":"operation1","plan_id":"plan1","plan_hash":"sha-plan","status":"stale","phase":"preview","created_at":"2026-10-28T15:00:00Z","updated_at":"2026-10-28T15:01:00Z","accepted_snapshot":{"workspace_hash":"work","dataset_hash":"data","model_hashes":[],"settings_hash":"settings"},"error":"Dataset changed"}
        """.utf8))
        try require(execution.status == "stale" && execution.error == "Dataset changed", "stale execution is an explicit error rather than success")

        func event(sequence: Int, call: String, stage: String, at: String) throws -> PlatformToolEvent {
            let wire: [String: JSONValue] = ["id": .string("e\(sequence)"), "sequence": .number(Double(sequence)), "project_id": .string("project1"), "operation_id": .string("operation1"), "call_id": .string(call), "kind": .string("tool"), "stage": .string(stage), "name": .string("preview_pipeline"), "phase": .string("preview"), "at": .string(at), "duration_ms": .null, "input_artifact_id": .string("opaque-input"), "error": stage == "failed" ? .string("Inference failed") : .null]
            return try JSONDecoder().decode(PlatformToolEvent.self, from: JSONEncoder().encode(wire))
        }
        let started = try event(sequence: 1, call: "first", stage: "started", at: "later-clock")
        let failed = try event(sequence: 2, call: "first", stage: "failed", at: "earlier-clock")
        let active = try event(sequence: 3, call: "second", stage: "started", at: "clock")
        let events = [active, failed, started]
        try require(PlatformTimeline.ordered(events).map(\.sequence) == [1, 2, 3], "timeline order uses server sequence rather than local time or response order")
        try require(PlatformTimeline.activeCallIDs(events) == ["second"], "terminal failure removes its active spinner while other calls remain active")
        try require(PlatformTimeline.currentEvent(events, running: true)?.callID == "second", "compact timeline displays the actual active action")
        try require(PlatformTimeline.currentEvent([failed, started], running: false)?.stage == "failed", "compact completed timeline preserves the latest failure")
        try require(PlatformTimeline.currentEvent([], running: true) == nil, "empty timeline does not invent a current step")
        try require(failed.durationMs == nil && failed.error == "Inference failed" && failed.outputArtifactID == nil, "failed action does not fabricate duration or output")
        let artifact = try JSONDecoder().decode(PlatformArtifactContent.self, from: Data("""
        {"artifact":{"id":"opaque-output","project_id":"project1","kind":"tool_output","title":"Preview output","created_at":"2026-10-28T15:00:00Z","sha256":"recordedhash","media_type":"application/json","size_bytes":26},"content":{"result":{"detections":[]},"warnings":["No objects found"]}}
        """.utf8))
        try require(artifact.content["warnings"] == .array([.string("No objects found")]) && artifact.artifact.id == "opaque-output", "artifact detail uses server content and opaque reference")
        try require(PlatformTimeline.pathComponent("opaque/id?x#y") == "opaque%2Fid%3Fx%23y", "artifact reference cannot inject another HTTP route")
        try require(PlatformPresentation.duration(1.25) == "1.2 s" && PlatformPresentation.duration(nil) == "—", "timing is actual seconds with missing values distinct from zero")
        return checks
    }
}
