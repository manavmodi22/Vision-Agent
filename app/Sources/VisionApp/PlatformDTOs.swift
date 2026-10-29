import Foundation

struct PlanSnapshot: Codable {
    let workspaceHash: String
    let datasetHash: String
    let modelHashes: [String]
    let settingsHash: String
    enum CodingKeys: String, CodingKey { case workspaceHash = "workspace_hash", datasetHash = "dataset_hash", modelHashes = "model_hashes", settingsHash = "settings_hash" }
}
struct PlanMetric: Codable {
    let candidateIndex: Int
    let metric: String
    let target: Double
    let direction: String
    enum CodingKeys: String, CodingKey { case candidateIndex = "candidate_index", metric, target, direction }
    var targetLabel: String { (direction == "minimize" ? "≤ " : "≥ ") + String(format: "%.3g", target) }
}
struct PlanExperiment: Codable, Identifiable {
    let id: String
    let phase: String
    let description: String
    let allowedTools: [String]
    let candidateIndices: [Int]
    enum CodingKeys: String, CodingKey { case id, phase, description, allowedTools = "allowed_tools", candidateIndices = "candidate_indices" }
}
struct HumanCheckpoint: Codable, Identifiable {
    let id: String
    let phase: String
    let description: String
    let requiresApproval: Bool
    enum CodingKeys: String, CodingKey { case id, phase, description, requiresApproval = "requires_approval" }
}
struct PlanSkill: Codable, Identifiable {
    let id: String
    let version: String
    let sha256: String
}
struct PlanCandidateModelSelection: Codable {
    let candidateIndex: Int
    let capabilityID: String
    let modelID: String
    let adapterID: String
    let proposedReason: String
    let optionsSnapshotID: String
    let status: String
    enum CodingKeys: String, CodingKey {
        case candidateIndex = "candidate_index", capabilityID = "capability_id", modelID = "model_id"
        case adapterID = "adapter_id", proposedReason = "proposed_reason", optionsSnapshotID = "options_snapshot_id", status
    }
}
struct PlatformBuildPlan: Codable, Identifiable {
    let id: String
    let projectID: String
    let buildID: String?
    let operationID: String
    let revision: Int
    let parentPlanID: String?
    let createdAt: String
    let contentHash: String
    let goal: String
    let assumptions: [String]
    let candidates: [Pipeline]
    let requiredCapabilities: [String]
    let experiments: [PlanExperiment]
    let metrics: [PlanMetric]
    let stopConditions: [String]
    let humanCheckpoints: [HumanCheckpoint]
    let snapshot: PlanSnapshot
    let skills: [PlanSkill]
    let revisionReason: String
    let modelSelections: [PlanCandidateModelSelection]?
    let planningOptionsArtifactID: String?
    func modelSelections(for candidateIndex: Int) -> [PlanCandidateModelSelection] {
        (modelSelections ?? []).filter { $0.candidateIndex == candidateIndex }
    }
    enum CodingKeys: String, CodingKey {
        case id, revision, goal, assumptions, candidates, experiments, metrics, snapshot, skills
        case projectID = "project_id", buildID = "build_id", operationID = "operation_id", parentPlanID = "parent_plan_id"
        case createdAt = "created_at", contentHash = "content_hash", requiredCapabilities = "required_capabilities"
        case stopConditions = "stop_conditions", humanCheckpoints = "human_checkpoints", revisionReason = "revision_reason"
        case modelSelections = "model_selections", planningOptionsArtifactID = "planning_options_artifact_id"
    }
}
struct PlatformExecution: Codable, Identifiable {
    let id: String
    let projectID: String
    let buildID: String?
    let operationID: String
    let planID: String
    let planHash: String
    let status: String
    let phase: String
    let createdAt: String
    let updatedAt: String
    let acceptedSnapshot: PlanSnapshot
    let error: String?
    enum CodingKeys: String, CodingKey {
        case id, status, phase, error, projectID = "project_id", buildID = "build_id", operationID = "operation_id"
        case planID = "plan_id", planHash = "plan_hash", createdAt = "created_at", updatedAt = "updated_at", acceptedSnapshot = "accepted_snapshot"
    }
}
struct PlatformArtifact: Codable, Identifiable {
    let id: String
    let projectID: String
    let kind: String
    let title: String
    let createdAt: String
    let sha256: String
    let mediaType: String
    let sizeBytes: Int
    enum CodingKeys: String, CodingKey { case id, kind, title, sha256, projectID = "project_id", createdAt = "created_at", mediaType = "media_type", sizeBytes = "size_bytes" }
}
struct PlatformArtifactContent: Codable {
    let artifact: PlatformArtifact
    let content: [String: JSONValue]
}
struct PlatformToolEvent: Codable, Identifiable {
    let id: String
    let sequence: Int
    let projectID: String
    let buildID: String?
    let operationID: String
    let executionID: String?
    let planID: String?
    let callID: String
    let kind: String
    let stage: String
    let name: String
    let phase: String
    let at: String
    let durationMs: Double?
    let modelIdentity: String?
    let costUSD: Double?
    let inputArtifactID: String
    let outputArtifactID: String?
    let error: String?
    enum CodingKeys: String, CodingKey {
        case id, sequence, kind, stage, name, phase, at, error, projectID = "project_id", buildID = "build_id", operationID = "operation_id"
        case executionID = "execution_id", planID = "plan_id", callID = "call_id", durationMs = "duration_ms", modelIdentity = "model_identity"
        case costUSD = "cost_usd", inputArtifactID = "input_artifact_id", outputArtifactID = "output_artifact_id"
    }
}

enum PlatformTimeline {
    static func currentEvent(_ events: [PlatformToolEvent], running: Bool) -> PlatformToolEvent? {
        let orderedEvents = ordered(events)
        let active = running ? activeCallIDs(orderedEvents) : []
        return orderedEvents.last(where: { $0.stage == "started" && active.contains($0.callID) }) ?? orderedEvents.last
    }
    static func pathComponent(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))) ?? ""
    }
    static func ordered(_ events: [PlatformToolEvent]) -> [PlatformToolEvent] {
        events.sorted { $0.sequence == $1.sequence ? $0.id < $1.id : $0.sequence < $1.sequence }
    }
    static func activeCallIDs(_ events: [PlatformToolEvent]) -> Set<String> {
        var active: Set<String> = []
        for event in ordered(events) {
            if event.stage == "started" { active.insert(event.callID) } else { active.remove(event.callID) }
        }
        return active
    }
}
