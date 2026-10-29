import Foundation

struct ProvisioningArtifact: Codable {
    let filename: String
    let sourceURL: String
    let expectedSHA256: String
    let expectedBytes: Int64
    enum CodingKeys: String, CodingKey { case filename, sourceURL = "source_url", expectedSHA256 = "expected_sha256", expectedBytes = "expected_bytes" }
}
struct ProvisioningOption: Decodable, Identifiable {
    let modelID: String
    let capabilityID: String
    let name: String
    let action: String
    let installed: Bool
    let downloadBytes: Int64
    let blockers: [String]
    var id: String { modelID }
    enum CodingKeys: String, CodingKey { case modelID = "model_id", capabilityID = "capability_id", name, action, installed, downloadBytes = "download_bytes", blockers }
}
struct ProvisioningOptions: Decodable { let options: [ProvisioningOption] }
struct ProvisioningPlan: Decodable, Identifiable {
    let id: String
    let planHash: String
    let createdAt: String
    let modelID: String
    let capabilityID: String
    let name: String
    let action: String
    let artifacts: [ProvisioningArtifact]
    let license: CapabilityLicense
    let sourceRevision: String
    let targetDirectory: String
    let totalDownloadBytes: Int64
    let maxDurationS: Int
    let hardware: CapabilityHardware
    let readiness: CapabilityReadiness
    let blockers: [String]
    let runtimeSnapshot: [String: String]
    let existingInstallationHash: String?
    enum CodingKeys: String, CodingKey {
        case id, planHash = "plan_hash", createdAt = "created_at", modelID = "model_id", capabilityID = "capability_id", name, action, artifacts, license
        case sourceRevision = "source_revision", targetDirectory = "target_directory", totalDownloadBytes = "total_download_bytes", maxDurationS = "max_duration_s"
        case hardware, readiness, blockers, runtimeSnapshot = "runtime_snapshot", existingInstallationHash = "existing_installation_hash"
    }
}
struct ProvisioningResult: Decodable {
    let installed: Bool
    let installationPath: String
    let artifactHashes: [String: String]
    let smokeStatus: String
    let healthReceiptID: String?
    let message: String
    enum CodingKeys: String, CodingKey { case installed, installationPath = "installation_path", artifactHashes = "artifact_hashes", smokeStatus = "smoke_status", healthReceiptID = "health_receipt_id", message }
}
struct ProvisioningJob: Decodable, Identifiable {
    let id: String
    let planID: String
    let planHash: String
    let modelID: String
    let status: String
    let phase: String
    let createdAt: String
    let updatedAt: String
    let progress: Double
    let downloadedBytes: Int64
    let totalBytes: Int64
    let message: String
    let error: String?
    let result: ProvisioningResult?
    var active: Bool { ["queued", "running"].contains(status) }
    var terminal: Bool { ["completed", "failed", "interrupted"].contains(status) }
    enum CodingKeys: String, CodingKey {
        case id, planID = "plan_id", planHash = "plan_hash", modelID = "model_id", status, phase, createdAt = "created_at", updatedAt = "updated_at"
        case progress, downloadedBytes = "downloaded_bytes", totalBytes = "total_bytes", message, error, result
    }
}
struct ProvisioningApproval: Encodable {
    let planID: String
    let planHash: String
    let approved: Bool
    enum CodingKeys: String, CodingKey { case planID = "plan_id", planHash = "plan_hash", approved }
}
struct ProvisioningHealth: Decodable {
    let id: String
    let modelID: String
    let jobID: String
    let planHash: String
    let createdAt: String
    let installationHash: String
    let runtimeSnapshot: [String: String]
    let inputDescription: String
    let inputSHA256: String
    let elapsedS: Double
    let observationCount: Int
    let executionIdentityHash: String
    let qualityClaim: String
    enum CodingKeys: String, CodingKey {
        case id, modelID = "model_id", jobID = "job_id", planHash = "plan_hash", createdAt = "created_at", installationHash = "installation_hash"
        case runtimeSnapshot = "runtime_snapshot", inputDescription = "input_description", inputSHA256 = "input_sha256"
        case elapsedS = "elapsed_s", observationCount = "observation_count", executionIdentityHash = "execution_identity_hash", qualityClaim = "quality_claim"
    }
}
enum ProvisioningPresentation {
    static func canApprove(_ plan: ProvisioningPlan?) -> Bool {
        guard let plan else { return false }
        return ["install", "validate"].contains(plan.action) && plan.blockers.isEmpty
    }
    static func actionTitle(_ action: String) -> String { action == "install" ? "Install and test" : "Validate installation" }
    static func resultTitle(_ result: ProvisioningResult) -> String {
        if result.installed && result.smokeStatus == "passed" { return "Installed · adapter validation passed" }
        if result.installed { return "Installed · execution readiness not verified" }
        return "Installation not completed"
    }
    static func jobMatches(_ job: ProvisioningJob, plan: ProvisioningPlan) -> Bool {
        job.modelID == plan.modelID && job.planID == plan.id && job.planHash == plan.planHash
    }
    static func receiptMatches(_ receipt: ProvisioningHealth, job: ProvisioningJob, plan: ProvisioningPlan) -> Bool {
        job.status == "completed" && job.result?.installed == true && job.result?.smokeStatus == "passed" && jobMatches(job, plan: plan) && receipt.id == job.result?.healthReceiptID &&
        receipt.modelID == job.modelID && receipt.jobID == job.id && receipt.planHash == plan.planHash && receipt.qualityClaim == "none"
    }
}
