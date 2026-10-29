import Foundation

extension AgentWorkspaceStore {
    private var investigationPath: String { "/projects/\(PlatformTimeline.pathComponent(projectID))/investigations" }
    func bindRuntime(_ value: AgentRuntime) {
        runtime = value; sessionResolved = true
        UserDefaults.standard.set(value.rawValue, forKey: "vision.agentRuntime.\(projectID)")
    }
    func resolveSession() async throws {
        guard !sessionResolved else { return }
        if runtime != nil { sessionResolved = true; return }
        var buildConflict: EngineError?
        do {
            let response: AgentBuildStatus = try await client.request("GET", "/projects/\(projectID)/build")
            guard runtime == nil else { return }
            build = response; retainInvestigationOrigin(response); bindRuntime(.legacy); return
        } catch EngineError.server(404, _) { }
        catch EngineError.server(409, let message) { buildConflict = .server(409, message) }
        let tasks: [InvestigationState] = try await client.request("GET", investigationPath)
        guard runtime == nil else { return }
        if let buildConflict {
            // A durable handoff journal may intentionally block /build before
            // the imported build exists. Recovery must not depend on local prefs.
            for task in tasks {
                do {
                    let status: InvestigationHandoffStatus = try await client.request("GET", investigationPath + "/" + PlatformTimeline.pathComponent(task.id) + "/handoff")
                    if try recoverHandoffSession(task: task, status: status) { return }
                } catch EngineError.server(404, _) { continue }
            }
            throw buildConflict
        }
        if let latest = tasks.first { bindRuntime(.investigation); retainTask(latest.id) }
        sessionResolved = true
    }
    func retainTask(_ id: String) {
        investigationTaskID = id
        UserDefaults.standard.set(id, forKey: "vision.investigationTask.\(projectID)")
    }
    func refreshInvestigation() async throws {
        guard usingInvestigation else { return }
        if investigationTaskID == nil {
            let tasks: [InvestigationState] = try await client.request("GET", investigationPath)
            if let latest = tasks.first { retainTask(latest.id) } else { return }
        }
        guard let id = investigationTaskID else { return }
        let snapshot: InvestigationSnapshot = try await client.request("GET", investigationPath + "/" + PlatformTimeline.pathComponent(id))
        guard usingInvestigation, investigationTaskID == id,
              InvestigationPresentation.accepts(snapshot.state, current: investigation?.state, projectID: projectID, taskID: id) else { return }
        investigation = snapshot
        if submittedGoal == snapshot.state.objective { retainSubmission(nil) }
        let startKey = "vision.investigationStart.\(projectID)"
        if let pending = UserDefaults.standard.dictionary(forKey: startKey), pending["objective"] as? String == snapshot.state.objective {
            UserDefaults.standard.removeObject(forKey: startKey)
        }
        if ["draft_ready", "inconclusive"].contains(snapshot.state.status), snapshot.selectedDraft != nil,
           handoffCheckedTaskID != id || handoffStatus?.status == "committing" {
            do { try await refreshHandoffStatus(taskID: id) } catch { handoffError = error.localizedDescription }
        }
    }
    func startInvestigation(objective: String) async throws {
        guard !investigationRequestPending, !handoffInProgress else { return }
        guard investigation == nil || investigation?.state.terminal == true else {
            throw EngineError.protocolError("Resume or cancel the current investigation before starting another.")
        }
        bindRuntime(.investigation)
        investigationRequestPending = true; defer { investigationRequestPending = false }
        let key = "vision.investigationStart.\(projectID)"
        let saved = UserDefaults.standard.dictionary(forKey: key) as? [String: String]
        if let saved, saved["objective"] != objective {
            throw EngineError.protocolError("The earlier start request has not been reconciled. Retry its original objective first.")
        }
        let requestID = saved?["requestID"] ?? UUID().uuidString
        UserDefaults.standard.set(["objective": objective, "requestID": requestID], forKey: key)
        retainSubmission(objective)
        let response: InvestigationState
        do {
            response = try await client.request("POST", investigationPath, body: ["runtime_version": .string("a0.1"), "objective": .string(objective), "client_request_id": .string(requestID)])
        } catch EngineError.server(let status, let message) where (400..<500).contains(status) {
            UserDefaults.standard.removeObject(forKey: key)
            throw EngineError.server(status, message)
        }
        guard response.projectID == projectID, response.supported else { throw EngineError.protocolError("Unexpected investigation response.") }
        retainTask(response.id)
        handoffStatus = nil; handoffError = nil; handoffCheckedTaskID = nil
        investigation = InvestigationSnapshot(state: response, actions: [], observations: [])
        UserDefaults.standard.removeObject(forKey: key)
        retainSubmission(nil); error = nil
        // A polling failure does not turn an acknowledged start into a new submission.
        do { try await refreshInvestigation() } catch { self.error = error.localizedDescription }
    }
    func resumeInvestigation(answer: String? = nil) async throws {
        guard let state = investigation?.state, state.resumable, !investigationRequestPending else { return }
        try await mutateInvestigation(state, suffix: "resume", body: InvestigationPresentation.resumeBody(state, answer: answer))
    }
    func controlInvestigation(_ action: String) async throws {
        guard let state = investigation?.state, state.cancellable, !investigationRequestPending,
              action == "cancel" || (action == "pause" && state.running) else { return }
        try await mutateInvestigation(state, suffix: "control", body: InvestigationPresentation.controlBody(state, action: action))
    }
    private func mutateInvestigation(_ state: InvestigationState, suffix: String, body: [String: JSONValue]) async throws {
        investigationRequestPending = true; defer { investigationRequestPending = false }
        do {
            let response: InvestigationState = try await client.request("POST", investigationPath + "/" + PlatformTimeline.pathComponent(state.id) + "/" + suffix, body: body)
            if investigationTaskID == state.id, InvestigationPresentation.accepts(response, current: investigation?.state, projectID: projectID, taskID: state.id) {
                investigation?.state = response
            }
            error = nil
        } catch {
            let original = error
            try? await refreshInvestigation()
            self.error = original.localizedDescription
            throw original
        }
        do { try await refreshInvestigation() } catch { self.error = error.localizedDescription }
    }
}
