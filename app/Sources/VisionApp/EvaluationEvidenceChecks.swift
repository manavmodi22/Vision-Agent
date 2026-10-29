import Foundation

enum EvaluationEvidenceChecks {
    @MainActor static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Evidence check failed: " + message) }; checks += 1
        }
        let historical = Evaluation(precision: 1, recall: 1, countMae: 0, passed: true, metric: "recall", target: 0.9, sampleCount: 10, failures: [], specHash: "spec", datasetHash: "data", textAccuracy: nil)
        let decoded = try JSONDecoder().decode(Evaluation.self, from: JSONEncoder().encode(historical))
        try require(decoded.promotionEligible == nil && !EvaluationEvidencePresentation.hasProtocol(decoded) && !EvaluationEvidencePresentation.canPromote(decoded), "historical numeric pass never implies quality or trial eligibility")
        var current = historical
        current.protocolID = "protocol"; current.protocolHash = "hash"; current.evidenceScope = "validation"; current.promotionEligible = false
        current.evidenceReasons = ["Unknown scene groups", "Correlated source frames"]
        try require(current.passed && !EvaluationEvidencePresentation.canPromote(current) && EvaluationEvidencePresentation.reasons(current).count == 2, "numeric pass remains separate from unknown/correlated quality evidence")
        try require(EvaluationEvidencePresentation.hasProtocol(current), "current validation can support deliberate trial without promotion")
        current.promotionEligible = true
        try require(!EvaluationEvidencePresentation.canPromote(current), "validation cannot claim independent acceptance even with malformed eligibility")
        current.evidenceScope = "acceptance"
        try require(EvaluationEvidencePresentation.canPromote(current), "passing eligible acceptance is promotable")
        current.passed = false
        try require(!EvaluationEvidencePresentation.canPromote(current), "eligible acceptance that misses its target is not promotable")
        current.evidenceScope = "sample"; current.promotionEligible = false
        try require(!EvidenceApprovalPresentation.canApprove(current, scope: .localTrial, reason: "") && EvidenceApprovalPresentation.canApprove(current, scope: .localTrial, reason: "Supervised local trial"), "sample trial needs an explicit substantive reason even with current evidence")
        try require(!EvidenceApprovalPresentation.canApprove(historical, scope: .localTrial, reason: "Supervised local trial"), "a trial reason does not bypass legacy re-evaluation")
        let configuration = try JSONDecoder().decode(EvaluationConfiguration.self, from: Data("""
        {"revision":"snapshot-a","images":[{"image_path":"/one/frame.png","source_asset_id":"clip-a","source_sha256":"sourcehash","frame_index":12,"timestamp_s":6.0,"scene_group":null,"split":"validation","data_origin":"real","group_provenance":"source_record","exposure_reasons":["Previewed during development"]},{"image_path":"/two/fixture.png","source_asset_id":null,"source_sha256":null,"frame_index":null,"timestamp_s":null,"scene_group":"fixture","split":"unassigned","data_origin":"synthetic","group_provenance":"source_record","exposure_reasons":[]}],"policy":{"intended_use":"Count in dock A","independent_group_basis":"Different recording sessions","required_acceptance_groups":["dock-b"],"coverage_rationale":"Daytime dock B only"}}
        """.utf8))
        try require(configuration.images[0].sceneGroup == nil && configuration.images[0].exposureReasons.count == 1 && configuration.images[1].sourceSHA256 == nil, "unknown source metadata remains unknown and actual exposure survives decode")
        let store = EvaluationEvidenceStore(projectID: "test", client: EngineClient(socketPath: "/unused-test-socket"))
        store.draft = configuration; store.selected = [configuration.images[0].id, configuration.images[1].id]
        store.assign(group: " scene-1 ", split: "acceptance", origin: "real")
        try require(store.images[0].sceneGroup == "scene-1" && store.images[0].split == "acceptance" && store.images[1].dataOrigin == "synthetic", "group edits normalize names but cannot reclassify known synthetic data")
        try require(store.images[0].sourceAssetID == "clip-a" && store.images[0].sourceSHA256 == "sourcehash" && store.images[0].exposureReasons == configuration.images[0].exposureReasons, "assignments cannot rewrite source identity or prior exposure")
        store.assign(group: "", split: nil, origin: nil)
        let wire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(EvaluationConfigurationRequest(store.draft!))).object
        guard case .array(let assignments) = wire["assignments"] else { throw EngineError.protocolError("Missing evidence assignments") }
        try require(wire["expected_revision"] == .string("snapshot-a") && assignments[0].object["scene_group"] == .null, "save carries original revision and explicit null when clearing a group")
        try require(Set(assignments[0].object.keys) == Set(["image_path", "scene_group", "split", "data_origin"]), "configuration save cannot change review flags, labels, source provenance, or exposure")
        store.conflict = true; let preserved = store.draft; store.assign(group: "new", split: "train", origin: "unknown")
        try require(store.draft == preserved, "conflicted draft is preserved until explicit reload")
        let trial = EvidenceApprovalRequest(candidateIndex: 1, approved: true, approvalScope: .localTrial, overrideReason: "Limited supervised trial")
        let request = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(trial)).object
        try require(request["approval_scope"] == .string("local_trial") && request["override_reason"] == .string("Limited supervised trial") && request["candidate_index"] == .number(1), "local trial is explicit on the wire with its own reason")
        let readiness = try JSONDecoder().decode(EvaluationReadiness.self, from: Data("{\"candidate_index\":1,\"acceptance_available\":false,\"acceptance_blockers\":[\"Source overlaps development data\"],\"current_acceptance\":null}".utf8))
        try require(!readiness.acceptanceAvailable && readiness.currentAcceptance == nil && readiness.acceptanceBlockers == ["Source overlaps development data"], "acceptance availability derives from the server's blocker check")
        try require(EvaluationEvidencePresentation.imagePath("media/a.png", projectMedia: ["/project/media/a.png"]) == "/project/media/a.png", "project-relative evidence resolves through actual project media")
        try require(EvaluationEvidencePresentation.imagePath("media/a.png", projectMedia: ["/one/media/a.png", "/two/media/a.png"]) == nil, "ambiguous relative image never displays a guessed source")
        let recovered = EvaluationReservation.rebase(configuration, newIDs: [configuration.images[1].id])
        try require(recovered.revision == configuration.revision && recovered.policy == configuration.policy && recovered.images[0] == configuration.images[0] && recovered.images[1].split == "acceptance", "reservation retry rebases only retained new IDs onto current revision and policy without reimport")
        var project = Project(id: "p", name: "Example", useCase: "custom", status: "approved", createdAt: "", updatedAt: "", media: [], candidates: [], evaluations: [], messages: [], synthetic: false, deploymentId: "old")
        try require(!EvidenceApprovalPresentation.hasRecordingApproval(project), "legacy deployment ID alone does not enable recording")
        project.approvalScope = "local_trial"; project.trialLimits = ["max_frames_per_run": 500]
        try require(EvidenceApprovalPresentation.hasRecordingApproval(project) && EvidenceApprovalPresentation.projectStatus(project) == "Local trial approved" && EvidenceApprovalPresentation.trialLimits(project) == ["Up to 500 frames per recorded run"], "persisted trial is labeled distinctly with actual server limits")
        return checks
    }
}
