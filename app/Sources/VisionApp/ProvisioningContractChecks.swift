import Foundation

enum ProvisioningContractChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Provisioning check failed: " + message) }; checks += 1
        }
        let options = try JSONDecoder().decode(ProvisioningOptions.self, from: Data("""
        {"options":[{"model_id":"model-a","capability_id":"model.capability-a","name":"Example","action":"install","installed":false,"download_bytes":9876,"blockers":[]}]}
        """.utf8))
        try require(options.options[0].id == "model-a" && options.options[0].capabilityID == "model.capability-a", "registry model and catalog capability identities remain distinct")
        let planData = Data("""
        {"id":"plan-a","plan_hash":"hash-a","created_at":"2026-10-29T00:00:00Z","model_id":"model-a","capability_id":"model.capability-a","name":"Example","action":"install","artifacts":[{"filename":"model.onnx","source_url":"https://example.org/pinned/model.onnx","expected_sha256":"artifact-sha","expected_bytes":9876}],"license":{"identifier":"Scoped licenses","code":"Apache-2.0","weights":"See upstream weight license","status":"declared","notes":["Code attribution does not replace weight terms"]},"source_revision":"revision-a","target_directory":"/models/model-a","total_download_bytes":9876,"max_duration_s":600,"hardware":{"platforms":["macOS"],"accelerators":["CPU"],"required_packages":["onnxruntime"],"minimum_memory_gib":null,"estimated_disk_bytes":12345,"notes":[]},"readiness":{"state":"unchecked","reason":"Adapter has not run","checked_at":"2026-10-29T00:00:00Z","evidence_scope":"prerequisites","evidence":[]},"blockers":[],"runtime_snapshot":{"python":"3.12","engine":"engine-hash"},"existing_installation_hash":null}
        """.utf8)
        let plan = try JSONDecoder().decode(ProvisioningPlan.self, from: planData)
        try require(plan.artifacts[0].expectedBytes == 9876 && plan.artifacts[0].sourceURL == "https://example.org/pinned/model.onnx" && plan.artifacts[0].expectedSHA256 == "artifact-sha", "reviewed artifact bytes/source/hash are preserved")
        try require(plan.license.code == "Apache-2.0" && plan.license.weights == "See upstream weight license", "code and weight license scopes are not collapsed")
        try require(plan.hardware.minimumMemoryGiB == nil && plan.existingInstallationHash == nil && plan.runtimeSnapshot["engine"] == "engine-hash", "unknown memory/installation identity remain unknown and runtime snapshot survives")
        try require(ProvisioningPresentation.canApprove(plan), "unverified adapter may have an approvable installation plan without claiming readiness")
        var wire = try JSONDecoder().decode(JSONValue.self, from: planData).object
        wire["blockers"] = .array([.string("Required runtime package is unavailable")])
        let blocked = try JSONDecoder().decode(ProvisioningPlan.self, from: JSONEncoder().encode(wire))
        try require(!ProvisioningPresentation.canApprove(blocked), "readiness blockers prohibit approval in native UI")
        wire["blockers"] = .array([]); wire["action"] = .string("unrecognized_future_action")
        try require(!ProvisioningPresentation.canApprove(try JSONDecoder().decode(ProvisioningPlan.self, from: JSONEncoder().encode(wire))), "unknown plan actions cannot become implicit approvals")
        let approval = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(ProvisioningApproval(planID: plan.id, planHash: plan.planHash, approved: true))).object
        try require(Set(approval.keys) == Set(["plan_id", "plan_hash", "approved"]) && approval["plan_hash"] == .string("hash-a") && approval["approved"] == .bool(true), "approval binds the exact reviewed plan and cannot inject paths/URLs/commands")
        let jobData = Data("""
        {"id":"job-a","plan_id":"plan-a","plan_hash":"hash-a","model_id":"model-a","status":"failed","phase":"failed","created_at":"2026-10-29T00:00:00Z","updated_at":"2026-10-29T00:01:00Z","progress":0.9,"downloaded_bytes":9876,"total_bytes":9876,"message":"Weights installed; adapter check failed","error":"Unsupported input layout","result":{"installed":true,"installation_path":"/models/model-a","artifact_hashes":{"model.onnx":"artifact-sha"},"smoke_status":"failed","health_receipt_id":null,"message":"Retry validation after correcting runtime"}}
        """.utf8)
        let job = try JSONDecoder().decode(ProvisioningJob.self, from: jobData)
        try require(job.terminal && !job.active && job.progress == 0.9 && job.downloadedBytes == 9876, "partial failed progress is retained rather than fabricated as zero or complete")
        try require(job.result?.installed == true && job.result?.healthReceiptID == nil && ProvisioningPresentation.resultTitle(job.result!) == "Installed · execution readiness not verified", "installed files do not conceal failed validation or create a receipt")
        try require(ProvisioningPresentation.jobMatches(job, plan: plan), "durable job matches exact model/plan/hash")
        var jobWire = try JSONDecoder().decode(JSONValue.self, from: jobData).object
        for key in ["plan_id", "plan_hash", "model_id"] {
            var changed = jobWire; changed[key] = .string("other")
            try require(!ProvisioningPresentation.jobMatches(try JSONDecoder().decode(ProvisioningJob.self, from: JSONEncoder().encode(changed)), plan: plan), "stale or other-model job cannot attach through \(key)")
        }
        jobWire["status"] = .string("running"); jobWire["phase"] = .string("validating")
        let running = try JSONDecoder().decode(ProvisioningJob.self, from: JSONEncoder().encode(jobWire))
        try require(running.active && !running.terminal, "actual running state drives polling; a prior result does not imply completion")
        let healthData = Data("""
        {"id":"receipt-a","model_id":"model-a","job_id":"job-a","plan_hash":"hash-a","created_at":"2026-10-29T00:01:00Z","installation_hash":"installed-hash","runtime_snapshot":{"engine":"engine-hash"},"input_description":"Generated black RGB image, 640 by 640 pixels; no user media","input_sha256":"input-hash","elapsed_s":0.35,"observation_count":0,"execution_identity_hash":"execution-hash","quality_claim":"none"}
        """.utf8)
        let health = try JSONDecoder().decode(ProvisioningHealth.self, from: healthData)
        try require(health.elapsedS == 0.35 && health.observationCount == 0 && health.qualityClaim == "none" && health.inputDescription.contains("no user media"), "adapter receipt preserves actual smoke scope and zero observations without claiming task quality")
        jobWire["status"] = .string("completed")
        var success = jobWire["result"]!.object; success["smoke_status"] = .string("passed"); success["health_receipt_id"] = .string("receipt-a"); jobWire["result"] = .object(success)
        let completed = try JSONDecoder().decode(ProvisioningJob.self, from: JSONEncoder().encode(jobWire))
        try require(ProvisioningPresentation.receiptMatches(health, job: completed, plan: plan), "completed job's explicit receipt is matched to model, job and reviewed plan")
        let healthWire = try JSONDecoder().decode(JSONValue.self, from: healthData).object
        for key in ["id", "model_id", "job_id", "plan_hash", "quality_claim"] {
            var changed = healthWire; changed[key] = .string("other")
            try require(!ProvisioningPresentation.receiptMatches(try JSONDecoder().decode(ProvisioningHealth.self, from: JSONEncoder().encode(changed)), job: completed, plan: plan), "receipt mismatch in \(key) cannot become evidence for this job")
        }
        try require(!ProvisioningPresentation.receiptMatches(health, job: job, plan: plan), "a matching receipt cannot convert a failed job into passed evidence")
        return checks
    }
}
