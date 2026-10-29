import Foundation

enum InvestigationHandoffChecks {
    @MainActor static func run(snapshot fixture: InvestigationSnapshot) throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Investigation import check failed: " + message) }; checks += 1
        }
        func rejected(_ body: () throws -> Void) -> Bool { do { try body(); return false } catch { return true } }
        func decode<T: Decodable>(_ object: [String: JSONValue], as: T.Type = T.self) throws -> T { try JSONDecoder().decode(T.self, from: JSONEncoder().encode(object)) }
        let projectID = "native-handoff-" + UUID().uuidString
        var raw = try JSONDecoder().decode([String: JSONValue].self, from: JSONEncoder().encode(fixture))
        var state = raw["state"]!.object
        state["status"] = .string("draft_ready"); state["stage"] = .string("investigating"); state["project_id"] = .string(projectID)
        state["pending_action_id"] = .null; state["pending_model_call_id"] = .null; raw["state"] = .object(state)
        let snapshot: InvestigationSnapshot = try decode(raw)
        let task = snapshot.state.id, draft = snapshot.selectedDraft!
        let proposalID = String(repeating: "1", count: 32), buildID = String(repeating: "2", count: 32)
        let hash = String(repeating: "3", count: 64)
        var proposalJSON: [String: JSONValue] = ["schema_version": .string("a0.handoff.1"), "id": .string(proposalID), "project_id": .string(projectID), "task_id": .string(task), "task_revision": .number(Double(snapshot.state.revision)), "workflow_revision_id": .string(draft.revisionID), "preview_observation_id": .string(draft.observation.id), "proposal_hash": .string(hash), "original_spec_hash": .string(draft.specHash), "candidate_spec_hash": .string(String(repeating: "4", count: 64)), "source_before": .string("investigations/\(task)/workflows/\(draft.revisionID)/media"), "source_after": .string("media"), "original_media_count": .number(1), "project_media_count": .number(3), "candidate_name": .string("Read 東京 é"), "metric": .string("text_accuracy"), "target": .number(0), "limitations": .array([.string("Draft assumptions require review")]), "created_at": .string("now")]
        proposalJSON["origin_task_status"] = .string("draft_ready"); proposalJSON["origin_stop_reason"] = state["stop_reason"] ?? .null
        let proposal: InvestigationHandoffProposal = try decode(proposalJSON)
        try require(proposal.matches(snapshot) && proposal.target == 0 && proposal.candidateName == "Read 東京 é", "proposal matches exact selected preview and retains Unicode and zero target without a quality claim")
        try require(proposal.originalMediaCount == 1 && proposal.projectMediaCount == 3, "selected sample count remains distinct from future project media")
        let prepare = try InvestigationHandoffPresentation.prepareBody(snapshot)
        try require(Set(prepare.keys) == ["expected_revision", "workflow_revision_id", "preview_observation_id"] && prepare["workflow_revision_id"] == .string(draft.revisionID), "prepare sends host identities only, never a client graph or source path")
        for status in ["cancelled", "paused", "running", "failed"] {
            var changed = state; changed["status"] = .string(status); var value = raw; value["state"] = .object(changed)
            let other: InvestigationSnapshot = try decode(value)
            try require(!proposal.matches(other) && InvestigationHandoffPresentation.unavailability(other, candidateCount: 0) != nil, "\(status) cannot be imported solely because it has a saved preview")
        }
        var recoveredState = state; recoveredState["status"] = .string("inconclusive"); recoveredState["stop_reason"] = .string("The final agent decision omitted its preview citation")
        var recoveredJSON = raw; recoveredJSON["state"] = .object(recoveredState)
        let recovered: InvestigationSnapshot = try decode(recoveredJSON)
        var recoveryProposalJSON = proposalJSON; recoveryProposalJSON["origin_task_status"] = .string("inconclusive"); recoveryProposalJSON["origin_stop_reason"] = recoveredState["stop_reason"]
        let recoveryProposal: InvestigationHandoffProposal = try decode(recoveryProposalJSON)
        try require(recoveryProposal.matches(recovered) && recovered.state.status == "inconclusive", "explicit recovery can import a saved preview without relabelling the investigation complete")
        try require(!proposal.matches(recovered), "proposal must retain actual origin status and stop reason")
        recoveredJSON["observations"] = .array([])
        try require(InvestigationHandoffPresentation.unavailability(try decode(recoveredJSON), candidateCount: 0) != nil, "inconclusive task without a valid saved preview cannot be recovered")
        try require(InvestigationHandoffPresentation.unavailability(snapshot, candidateCount: 1) != nil, "existing candidates require backend conflict rather than replacement")
        for (field, value) in [("schema_version", JSONValue.string("future")), ("task_id", .string("other")), ("task_revision", .number(99)), ("source_after", .string("elsewhere")), ("original_spec_hash", .string(hash)), ("preview_observation_id", .string("other"))] {
            var changed = proposalJSON; changed[field] = value
            let other: InvestigationHandoffProposal = try decode(changed)
            try require(!other.matches(snapshot), "proposal rejects changed \(field)")
        }
        let requestKey = "vision.investigationHandoff.\(projectID).\(task)"
        let keys = [requestKey, "vision.agentRuntime.\(projectID)", "vision.investigationTask.\(projectID)"]
        defer { keys.forEach { UserDefaults.standard.removeObject(forKey: $0) } }
        let client = EngineClient(socketPath: "/no-handoff-test-connection")
        let store = AgentWorkspaceStore(projectID: projectID, client: client)
        store.bindRuntime(.investigation); store.retainTask(task); store.investigation = snapshot
        try require(rejected { _ = try store.handoffAcceptanceBody(proposal, acknowledged: false) } && UserDefaults.standard.object(forKey: requestKey) == nil, "unacknowledged source change cannot reserve acceptance")
        let first = try store.handoffAcceptanceBody(proposal, acknowledged: true)
        let restarted = AgentWorkspaceStore(projectID: projectID, client: client)
        let retried = try restarted.handoffAcceptanceBody(proposal, acknowledged: true)
        try require(first == retried && first["acknowledge_source_rebind"] == .bool(true), "retry and relaunch retain one exact acceptance request ID")
        proposalJSON["proposal_hash"] = .string(String(repeating: "5", count: 64))
        let different: InvestigationHandoffProposal = try decode(proposalJSON)
        try require(rejected { _ = try restarted.handoffAcceptanceBody(different, acknowledged: true) }, "unresolved request cannot silently switch proposals")
        let receiptJSON: [String: JSONValue] = ["schema_version": .string("a0.handoff.1"), "id": .string(String(repeating: "6", count: 32)), "project_id": .string(projectID), "task_id": .string(task), "workflow_revision_id": .string(draft.revisionID), "preview_observation_id": .string(draft.observation.id), "proposal_id": .string(proposalID), "proposal_hash": .string(hash), "client_request_id": first["client_request_id"]!, "build_id": .string(buildID), "candidate_index": .number(0), "original_spec_hash": .string(draft.specHash), "candidate_spec_hash": .string(proposal.candidateSpecHash), "created_at": .string("now"), "origin_task_status": .string("draft_ready"), "origin_stop_reason": state["stop_reason"] ?? .null]
        let receipt: InvestigationHandoffReceipt = try decode(receiptJSON)
        try require(receipt.matches(proposal) && !receipt.matches(different), "receipt identifies the accepted source/spec proposal exactly")
        let pipeline: JSONValue = .object(["spec_version": .string("0.1"), "name": .string("Imported fixture"), "inputs": .object(["source": .object(["type": .string("image_folder"), "path": .string("media")])]), "blocks": .array([]), "eval": .object(["metric": .string("text_accuracy"), "target": .number(0), "set": .string("eval")])])
        let project: JSONValue = .object(["id": .string(projectID), "name": .string("Import check"), "use_case": .string("custom"), "status": .string("draft"), "created_at": .string("now"), "updated_at": .string("now"), "media": .array([]), "brief": .null, "candidates": .array([pipeline]), "evaluations": .array([]), "messages": .array([]), "synthetic": .bool(true)])
        let preview = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(draft.preview))
        var buildJSON: [String: JSONValue] = ["id": .string(buildID), "project_id": .string(projectID), "status": .string("awaiting_review"), "phase": .string("awaiting_review"), "next_action": .string("review_labels"), "message": .string("Review the imported draft"), "questions": .array([]), "log": .array([]), "preview": preview, "selected_candidate_index": .number(0), "evaluations": .array([]), "project": project, "updated_at": .string("now")]
        let legacy: AgentBuildStatus = try decode(buildJSON)
        try require(legacy.investigationOrigin == nil, "existing builds decode without new origin metadata")
        buildJSON["investigation_origin"] = .object(receiptJSON)
        let build: AgentBuildStatus = try decode(buildJSON)
        try require(InvestigationHandoffPresentation.reviewSurface(build) == .annotations, "label-review response opens the existing annotation review surface")
        var configured = buildJSON; configured["next_action"] = .string("configure_evaluation")
        try require(InvestigationHandoffPresentation.reviewSurface(try decode(configured)) == .evidence, "evidence-configuration response opens the existing evidence editor")
        configured["next_action"] = .string("approve_deployment")
        try require(InvestigationHandoffPresentation.reviewSurface(try decode(configured)) == nil, "handoff never automatically opens or grants deployment approval")
        try require(receipt.matches(build, project: projectID, task: task) && build.preview?.frames.count == 1, "actual returned build and preview are bound to the durable origin")
        try require(!receipt.matches(build, project: "other", task: task) && !receipt.matches(legacy, project: projectID, task: task), "cross-project or originless build cannot be adopted")
        try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: receipt, build: nil, status: "completed", message: "Superseded by another build"), taskID: task)
        try require(restarted.usingInvestigation && restarted.build == nil, "completed receipt without current build never switches runtime or invents a build")
        buildJSON["id"] = .string("different-build")
        let mismatched: AgentBuildStatus = try decode(buildJSON)
        try require(rejected { try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: receipt, build: mismatched, status: "completed", message: nil), taskID: task) } && restarted.build == nil, "mismatched status build has no adoption effect")
        try require(rejected { try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: nil, build: nil, status: "completed", message: nil), taskID: task) }, "completed status requires a durable receipt")
        try require(rejected { try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: receipt, build: build, status: "future", message: nil), taskID: task) }, "unknown handoff status grants no transition")
        try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: receipt, build: build, status: "completed", message: nil), taskID: task)
        try require(restarted.runtime == .legacy && restarted.build?.id == buildID && restarted.build?.nextAction == "review_labels", "completed backend status opens the returned review build")
        try require(restarted.build?.project.deploymentId == nil && restarted.build?.evaluations.isEmpty == true, "imported review state confers no evaluation or approval")
        let reopened = AgentWorkspaceStore(projectID: projectID, client: client)
        try require(reopened.runtime == .legacy && reopened.investigationTaskID == task && reopened.build == nil, "relaunch remembers navigation origin but still loads real build from backend")
        try require(UserDefaults.standard.object(forKey: requestKey) == nil, "acknowledged completed transaction clears pending request cache")
        try restarted.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: nil, build: nil, status: "committing", message: nil), taskID: task)
        try require(restarted.handoffStatus?.status == "completed", "late in-flight status cannot regress a completed import")
        keys.forEach { UserDefaults.standard.removeObject(forKey: $0) }
        let fresh = AgentWorkspaceStore(projectID: projectID, client: client)
        let pendingStatus = InvestigationHandoffStatus(proposal: proposal, receipt: nil, build: nil, status: "committing", message: "Recovering saved commit")
        try require(fresh.runtime == nil && fresh.investigationTaskID == nil, "recovery starts without runtime or task preferences")
        try require(try fresh.recoverHandoffSession(task: snapshot.state, status: pendingStatus), "build conflict can recover matching handoff from backend inventory without local preferences")
        try require(fresh.usingInvestigation && fresh.handoffInProgress && fresh.handoffStatus?.status == "committing" && fresh.build == nil && fresh.investigation?.selectedDraft == nil, "pending recovery blocks new goals and exposes status without inventing a completed build or preview")
        try fresh.applyHandoffStatus(InvestigationHandoffStatus(proposal: proposal, receipt: receipt, build: build, status: "completed", message: nil), taskID: task)
        try require(fresh.runtime == .legacy && fresh.build?.id == buildID, "uncached journal recovery adopts only the returned completed build")
        let conflictJSON: [String: JSONValue] = ["status": .string("conflict"), "can_abort": .bool(true), "message": .string("Runtime identity changed"), "proposal": try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(proposal))]
        let conflict: InvestigationHandoffStatus = try decode(conflictJSON)
        try require(conflict.canAbort == true && conflict.status == "conflict", "backend conflict explicitly advertises discard eligibility")
        let discard = try InvestigationHandoffPresentation.discardBody(conflict, acknowledged: true)
        try require(discard == ["proposal_id": .string(proposal.id), "proposal_hash": .string(proposal.proposalHash), "acknowledge_discard": .bool(true)], "discard is explicit and bound to one proposal without accepting or approving it")
        try require(rejected { _ = try InvestigationHandoffPresentation.discardBody(conflict, acknowledged: false) }, "discard requires explicit human acknowledgment")
        try require(rejected { _ = try InvestigationHandoffPresentation.discardBody(pendingStatus, acknowledged: true) }, "active or nonconflicting import cannot be discarded by the UI")
        var noPermission = conflictJSON; noPermission.removeValue(forKey: "can_abort")
        try require(rejected { _ = try InvestigationHandoffPresentation.discardBody(try decode(noPermission), acknowledged: true) }, "older or missing discard capability fails closed")
        return checks
    }
}
