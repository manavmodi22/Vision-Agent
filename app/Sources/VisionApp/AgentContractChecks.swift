import Foundation

enum AgentContractChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Agent check failed: " + message) }; checks += 1
        }
        let response = try JSONDecoder().decode(AgentBuildStatus.self, from: Data("""
        {"id":"build1","project_id":"project1","status":"awaiting_review","phase":"awaiting_media","next_action":"attach_media","message":"Add representative examples.","questions":[],"log":[{"at":"2026-10-28T12:00:00+00:00","phase":"awaiting_media","message":"No sample media was supplied."}],"preview":null,"selected_candidate_index":null,"evaluations":[],"created_at":"2026-10-28T12:00:00+00:00","updated_at":"2026-10-28T12:00:00+00:00","project":{"id":"project1","name":"Count people","use_case":"custom","status":"draft","created_at":"2026-10-28T12:00:00+00:00","updated_at":"2026-10-28T12:00:00+00:00","media":[],"brief":null,"candidates":[],"evaluations":[],"messages":[],"synthetic":false}}
        """.utf8))
        try require(response.nextAction == "attach_media" && !response.running, "missing media is a resumable checkpoint")
        try require(response.log.first?.at == "2026-10-28T12:00:00+00:00", "work log timestamps use the actual ISO wire contract")
        try require(response.preview == nil && response.project.deploymentId == nil, "pending build does not invent preview or approval")
        let counts = PreviewPresentation.detectionCounts([
            Detection(label: "person", confidence: 0.8, box: [0, 0, 0.2, 0.2]),
            Detection(label: "forklift", confidence: 0.7, box: [0.3, 0.3, 0.6, 0.6]),
            Detection(label: "person", confidence: 0.9, box: [0.7, 0.1, 0.9, 0.8])])
        try require(counts == ["person": 2, "forklift": 1], "per-class counts come from actual detections")
        try require(PreviewPresentation.detectionCounts([]).isEmpty, "no detections creates no class count claims")
        try require(AgentConversation.pendingSubmission("Count people", messages: []) == "Count people", "submitted goal remains visible before planner commit")
        try require(AgentConversation.pendingSubmission("Count people", messages: [ChatMessage(role: "user", content: "Count people\n")]) == nil, "committed user message replaces local echo without duplication")
        try require(AgentConversation.pendingSubmission("Count people", messages: [ChatMessage(role: "assistant", content: "Count people")]) != nil, "assistant quotation does not swallow the human request")
        let status = "Mark and save region A."
        try require(!AgentConversation.shouldShowStatus(status, messages: [ChatMessage(role: "assistant", content: "I need actual region boundaries.\nMark and save region A.  ")]), "persisted assistant body absorbs duplicate status instructions")
        try require(AgentConversation.shouldShowStatus("Evaluation failed. Review the errors.", messages: [ChatMessage(role: "assistant", content: status)]), "new status evidence is not hidden by an older assistant message")
        try require(AgentConversation.shouldShowStatus(status, messages: [ChatMessage(role: "user", content: status)]), "a user quotation does not replace the agent status")
        return checks
    }
}
