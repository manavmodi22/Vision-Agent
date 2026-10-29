import Foundation

struct InvestigationHandoffProposal: Codable, Identifiable {
    let schemaVersion: String, id: String, projectID: String, taskID: String
    let taskRevision: Int
    let workflowRevisionID: String, previewObservationID: String, proposalHash: String
    let originalSpecHash: String, candidateSpecHash: String, sourceBefore: String, sourceAfter: String
    let originalMediaCount: Int, projectMediaCount: Int
    let candidateName: String, metric: String
    let originTaskStatus: String, originStopReason: String?
    let target: Double
    let limitations: [String]
    let createdAt: String
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", id, projectID = "project_id", taskID = "task_id", taskRevision = "task_revision"
        case workflowRevisionID = "workflow_revision_id", previewObservationID = "preview_observation_id", proposalHash = "proposal_hash"
        case originalSpecHash = "original_spec_hash", candidateSpecHash = "candidate_spec_hash", sourceBefore = "source_before", sourceAfter = "source_after"
        case originalMediaCount = "original_media_count", projectMediaCount = "project_media_count", candidateName = "candidate_name", metric, target, limitations, createdAt = "created_at"
        case originTaskStatus = "origin_task_status", originStopReason = "origin_stop_reason"
    }
    func matches(_ snapshot: InvestigationSnapshot) -> Bool {
        guard schemaVersion == "a0.handoff.1", sourceAfter == "media", !sourceBefore.isEmpty,
              originalMediaCount > 0, projectMediaCount > 0, target.isFinite,
              [proposalHash, originalSpecHash, candidateSpecHash].allSatisfy(InvestigationHandoffPresentation.isHash),
              snapshot.state.projectID == projectID, snapshot.state.id == taskID, snapshot.state.revision == taskRevision,
              originTaskStatus == snapshot.state.status, originStopReason == snapshot.state.stopReason,
              InvestigationHandoffPresentation.unavailability(snapshot, candidateCount: 0) == nil,
              let draft = snapshot.selectedDraft else { return false }
        return draft.revisionID == workflowRevisionID && draft.observation.id == previewObservationID && draft.specHash == originalSpecHash
    }
}

struct InvestigationHandoffReceipt: Codable, Equatable, Identifiable {
    let schemaVersion: String, id: String, projectID: String, taskID: String
    let workflowRevisionID: String, previewObservationID: String, proposalID: String, proposalHash: String
    let clientRequestID: String, buildID: String
    let candidateIndex: Int
    let originalSpecHash: String, candidateSpecHash: String, createdAt: String
    let originTaskStatus: String, originStopReason: String?
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", id, projectID = "project_id", taskID = "task_id"
        case workflowRevisionID = "workflow_revision_id", previewObservationID = "preview_observation_id"
        case proposalID = "proposal_id", proposalHash = "proposal_hash", clientRequestID = "client_request_id", buildID = "build_id", candidateIndex = "candidate_index"
        case originalSpecHash = "original_spec_hash", candidateSpecHash = "candidate_spec_hash", createdAt = "created_at"
        case originTaskStatus = "origin_task_status", originStopReason = "origin_stop_reason"
    }
    func matches(_ build: AgentBuildStatus, project: String, task: String) -> Bool {
        schemaVersion == "a0.handoff.1" && projectID == project && taskID == task && buildID == build.id
            && ["draft_ready", "inconclusive"].contains(originTaskStatus)
            && build.projectID == project && build.project.id == project && candidateIndex >= 0
            && [proposalHash, originalSpecHash, candidateSpecHash].allSatisfy(InvestigationHandoffPresentation.isHash)
            && build.investigationOrigin == self
    }
    func matches(_ proposal: InvestigationHandoffProposal) -> Bool {
        schemaVersion == proposal.schemaVersion && projectID == proposal.projectID && taskID == proposal.taskID
            && proposalID == proposal.id && proposalHash == proposal.proposalHash
            && workflowRevisionID == proposal.workflowRevisionID && previewObservationID == proposal.previewObservationID
            && originalSpecHash == proposal.originalSpecHash && candidateSpecHash == proposal.candidateSpecHash
            && originTaskStatus == proposal.originTaskStatus && originStopReason == proposal.originStopReason
    }
}
struct InvestigationHandoffStatus: Decodable {
    let proposal: InvestigationHandoffProposal?
    let receipt: InvestigationHandoffReceipt?
    let build: AgentBuildStatus?
    let status: String
    let message: String?
    let canAbort: Bool?
    enum CodingKeys: String, CodingKey { case proposal, receipt, build, status, message, canAbort = "can_abort" }
    init(proposal: InvestigationHandoffProposal?, receipt: InvestigationHandoffReceipt?, build: AgentBuildStatus?, status: String, message: String?, canAbort: Bool? = nil) {
        self.proposal = proposal; self.receipt = receipt; self.build = build; self.status = status; self.message = message; self.canAbort = canAbort
    }
}
struct InvestigationHandoffResult: Decodable {
    let receipt: InvestigationHandoffReceipt
    let build: AgentBuildStatus
}

enum InvestigationHandoffPresentation {
    enum ReviewSurface { case annotations, evidence }
    static func reviewSurface(_ build: AgentBuildStatus) -> ReviewSurface? {
        guard !build.running else { return nil }
        switch build.nextAction {
        case "review_labels": return .annotations
        case "configure_evaluation": return .evidence
        default: return nil
        }
    }
    static func isHash(_ value: String) -> Bool { value.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil }
    static func unavailability(_ snapshot: InvestigationSnapshot, candidateCount: Int) -> String? {
        guard snapshot.state.supported else { return "This investigation version cannot be imported for review." }
        guard ["draft_ready", "inconclusive"].contains(snapshot.state.status) else {
            return snapshot.selectedDraft == nil ? "Import becomes available when the agent finishes with a validated draft preview." : "A saved preview is available, but this investigation did not finish with a draft ready for review."
        }
        guard snapshot.state.pendingActionID == nil, snapshot.state.pendingModelCallID == nil else { return "Wait for the active investigation call to finish before importing." }
        guard snapshot.selectedDraft != nil else { return "There is no selected saved draft with a matching valid preview receipt to import." }
        guard candidateCount == 0 else { return "This app already has workflow candidates. Import currently requires an app with no candidates." }
        return nil
    }
    static func prepareBody(_ snapshot: InvestigationSnapshot) throws -> [String: JSONValue] {
        guard unavailability(snapshot, candidateCount: 0) == nil, let draft = snapshot.selectedDraft else { throw EngineError.protocolError("This investigation has no eligible selected draft to import.") }
        return ["expected_revision": .number(Double(snapshot.state.revision)), "workflow_revision_id": .string(draft.revisionID), "preview_observation_id": .string(draft.observation.id)]
    }
    static func acceptBody(_ proposal: InvestigationHandoffProposal, requestID: String, acknowledged: Bool) throws -> [String: JSONValue] {
        guard acknowledged else { throw EngineError.protocolError("Review and acknowledge the change to project media before importing.") }
        return ["proposal_id": .string(proposal.id), "proposal_hash": .string(proposal.proposalHash), "client_request_id": .string(requestID), "acknowledge_source_rebind": .bool(true)]
    }
    static func discardBody(_ status: InvestigationHandoffStatus, acknowledged: Bool) throws -> [String: JSONValue] {
        guard acknowledged, status.status == "conflict", status.canAbort == true, let proposal = status.proposal else { throw EngineError.protocolError("The engine has not offered an incomplete import that can be explicitly discarded.") }
        return ["proposal_id": .string(proposal.id), "proposal_hash": .string(proposal.proposalHash), "acknowledge_discard": .bool(true)]
    }
}
