import Foundation

extension AgentWorkspaceStore {
    private func handoffPath(_ task: String) -> String {
        "/projects/\(PlatformTimeline.pathComponent(projectID))/investigations/\(PlatformTimeline.pathComponent(task))/handoff"
    }
    private func handoffRequestKey(_ task: String) -> String { "vision.investigationHandoff.\(projectID).\(task)" }
    func retainInvestigationOrigin(_ response: AgentBuildStatus) {
        guard let receipt = response.investigationOrigin, receipt.matches(response, project: projectID, task: receipt.taskID) else { return }
        retainTask(receipt.taskID)
        // The backend build carries the durable origin. Local state is only a
        // navigation cache; an old runtime preference cannot create a build.
        if investigation?.state.id != receipt.taskID { investigation = nil }
    }
    @discardableResult func adoptHandoff(_ receipt: InvestigationHandoffReceipt, build response: AgentBuildStatus, taskID: String) throws -> AgentBuildStatus {
        guard receipt.matches(response, project: projectID, task: taskID) else { throw EngineError.protocolError("The imported build does not match its investigation receipt.") }
        build = response; retainInvestigationOrigin(response); bindRuntime(.legacy)
        UserDefaults.standard.removeObject(forKey: handoffRequestKey(taskID))
        error = nil; handoffError = nil
        return response
    }
    func refreshHandoffStatus(taskID: String) async throws {
        let response: InvestigationHandoffStatus = try await client.request("GET", handoffPath(taskID))
        try applyHandoffStatus(response, taskID: taskID)
    }
    func applyHandoffStatus(_ response: InvestigationHandoffStatus, taskID: String) throws {
        guard investigationTaskID == taskID else { return }
        try validateHandoffStatus(response, taskID: taskID)
        if handoffStatus?.status == "completed", response.status != "completed" { return }
        if response.status == "completed", let receipt = response.receipt, let imported = response.build {
            try adoptHandoff(receipt, build: imported, taskID: taskID)
        }
        handoffStatus = response; handoffCheckedTaskID = taskID; handoffError = nil
    }
    private func validateHandoffStatus(_ response: InvestigationHandoffStatus, taskID: String) throws {
        guard ["none", "prepared", "committing", "completed", "interrupted", "conflict"].contains(response.status) else { throw EngineError.protocolError("This engine returned an unsupported import status.") }
        if let proposal = response.proposal, proposal.projectID != projectID || proposal.taskID != taskID { throw EngineError.protocolError("Import proposal belongs to another investigation.") }
        if let receipt = response.receipt, receipt.schemaVersion != "a0.handoff.1" || receipt.projectID != projectID || receipt.taskID != taskID { throw EngineError.protocolError("Import receipt belongs to another investigation or unsupported version.") }
        if response.status == "completed" {
            guard let receipt = response.receipt else { throw EngineError.protocolError("Completed import has no durable receipt.") }
            if let imported = response.build, !receipt.matches(imported, project: projectID, task: taskID) { throw EngineError.protocolError("The imported build does not match its investigation receipt.") }
        }
    }
    @discardableResult func recoverHandoffSession(task: InvestigationState, status: InvestigationHandoffStatus) throws -> Bool {
        guard runtime == nil, task.projectID == projectID, task.supported, status.status != "none" else { return false }
        try validateHandoffStatus(status, taskID: task.id)
        // No preview is invented here; the next snapshot fetch restores the
        // immutable evidence while the recovered backend status remains visible.
        retainTask(task.id); bindRuntime(.investigation)
        investigation = InvestigationSnapshot(state: task, actions: [], observations: [])
        try applyHandoffStatus(status, taskID: task.id)
        return true
    }
    func prepareHandoff(refreshProposal: Bool = false) async throws {
        guard !handoffRequestPending, let snapshot = investigation else { return }
        handoffRequestPending = true; defer { handoffRequestPending = false }
        do {
            try await refreshHandoffStatus(taskID: snapshot.state.id)
            if handoffStatus?.status == "completed" { return }
            guard handoffStatus?.status != "committing" else { throw EngineError.protocolError("The import is still being committed. Check its status before retrying.") }
            guard handoffStatus?.status != "conflict" else { throw EngineError.protocolError("Resolve the incomplete import conflict before preparing another proposal.") }
            if !refreshProposal, let existing = handoffStatus?.proposal, existing.matches(snapshot) { return }
            guard refreshProposal || UserDefaults.standard.dictionary(forKey: handoffRequestKey(snapshot.state.id)) == nil else {
                throw EngineError.protocolError("An earlier import request is unresolved. Check its status before preparing another proposal.")
            }
            let response: InvestigationHandoffProposal = try await client.request("POST", handoffPath(snapshot.state.id) + "/prepare", body: InvestigationHandoffPresentation.prepareBody(snapshot))
            guard investigationTaskID == snapshot.state.id, response.matches(snapshot) else { throw EngineError.protocolError("The import proposal does not match the selected draft and its preview.") }
            // Only an explicit fresh proposal acknowledged by the backend may
            // replace a failed request key. Unknown/committing work is preserved.
            if refreshProposal { UserDefaults.standard.removeObject(forKey: handoffRequestKey(snapshot.state.id)) }
            handoffStatus = InvestigationHandoffStatus(proposal: response, receipt: nil, build: nil, status: "prepared", message: nil)
            handoffError = nil
        } catch { handoffError = error.localizedDescription; throw error }
    }
    func acceptHandoff(_ proposal: InvestigationHandoffProposal, acknowledged: Bool) async throws -> AgentBuildStatus {
        guard !handoffRequestPending, let snapshot = investigation, proposal.matches(snapshot) else { throw EngineError.protocolError("Refresh the selected draft and import proposal before accepting.") }
        let body = try handoffAcceptanceBody(proposal, acknowledged: acknowledged)
        guard let requestID = body["client_request_id"]?.string else { throw EngineError.protocolError("Import request identity is unavailable.") }
        handoffRequestPending = true; defer { handoffRequestPending = false }
        do {
            let result: InvestigationHandoffResult = try await client.request("POST", handoffPath(proposal.taskID) + "/accept", body: body)
            guard result.receipt.matches(proposal),
                  result.receipt.clientRequestID == requestID else { throw EngineError.protocolError("Import response does not match the accepted proposal and request.") }
            let response = try adoptHandoff(result.receipt, build: result.build, taskID: proposal.taskID)
            handoffStatus = InvestigationHandoffStatus(proposal: proposal, receipt: result.receipt, build: response, status: "completed", message: nil)
            return response
        } catch {
            let original = error
            // A lost reply must resolve the same transaction; never start a new
            // build or repeat inference merely because the connection failed.
            try? await refreshHandoffStatus(taskID: proposal.taskID)
            if handoffStatus?.status == "completed", let receipt = handoffStatus?.receipt, let response = handoffStatus?.build,
               receipt.matches(proposal), receipt.clientRequestID == requestID {
                return try adoptHandoff(receipt, build: response, taskID: proposal.taskID)
            }
            handoffError = original.localizedDescription; throw original
        }
    }
    func handoffAcceptanceBody(_ proposal: InvestigationHandoffProposal, acknowledged: Bool) throws -> [String: JSONValue] {
        let key = handoffRequestKey(proposal.taskID)
        let pending = UserDefaults.standard.dictionary(forKey: key) as? [String: String]
        if let pending, pending["proposalID"] != proposal.id || pending["proposalHash"] != proposal.proposalHash {
            throw EngineError.protocolError("Reconcile the earlier import request before accepting a different proposal.")
        }
        let requestID = pending?["requestID"] ?? UUID().uuidString
        let body = try InvestigationHandoffPresentation.acceptBody(proposal, requestID: requestID, acknowledged: acknowledged)
        UserDefaults.standard.set(["proposalID": proposal.id, "proposalHash": proposal.proposalHash, "requestID": requestID], forKey: key)
        return body
    }
    func discardIncompleteHandoff() async throws {
        guard !handoffRequestPending, let status = handoffStatus, let taskID = investigationTaskID else { return }
        let body = try InvestigationHandoffPresentation.discardBody(status, acknowledged: true)
        handoffRequestPending = true; defer { handoffRequestPending = false }
        do {
            let response: InvestigationHandoffStatus = try await client.request("POST", handoffPath(taskID) + "/abort", body: body)
            try applyHandoffStatus(response, taskID: taskID)
            guard response.status == "interrupted", response.canAbort != true else { throw EngineError.protocolError("The incomplete import has not been discarded. Check its status before continuing.") }
            UserDefaults.standard.removeObject(forKey: handoffRequestKey(taskID))
        } catch {
            let original = error
            try? await refreshHandoffStatus(taskID: taskID)
            handoffError = original.localizedDescription
            throw original
        }
    }
    func refreshInvestigationHistory() async throws {
        guard let taskID = build?.investigationOrigin?.taskID ?? investigationTaskID else { return }
        let response: InvestigationSnapshot = try await client.request("GET", "/projects/\(PlatformTimeline.pathComponent(projectID))/investigations/\(PlatformTimeline.pathComponent(taskID))")
        guard response.state.projectID == projectID, response.state.id == taskID else { throw EngineError.protocolError("Investigation history belongs to another app.") }
        investigation = response
    }
}
