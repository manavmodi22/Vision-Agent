import Foundation

enum AgentRuntime: String {
    case legacy, investigation = "a0.1"
    static var newAppDefault: Self { UserDefaults.standard.bool(forKey: "vision.experimentalInvestigations") ? .investigation : .legacy }
}

struct InvestigationBudget: Codable {
    let maxModelCalls: Int, maxActions: Int, maxProbes: Int
    let maxElapsedS: Double
    let modelCalls: Int, actions: Int, probes: Int
    let elapsedS: Double
    enum CodingKeys: String, CodingKey {
        case maxModelCalls = "max_model_calls", maxActions = "max_actions", maxProbes = "max_probes", maxElapsedS = "max_elapsed_s"
        case modelCalls = "model_calls", actions, probes, elapsedS = "elapsed_s"
    }
}
struct InvestigationState: Codable, Identifiable {
    let schemaVersion: String, id: String, projectID: String, objective: String
    let revision: Int
    let status: String, stage: String
    let selectedWorkflowRevision: String?, previewObservationID: String?
    let budget: InvestigationBudget
    let pendingActionID: String?, pendingModelCallID: String?
    let latestObservationIDs: [String]
    let question: String?, stopReason: String?
    let userAnswers: [String]
    let createdAt: String, updatedAt: String
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", id, projectID = "project_id", objective, revision, status, stage, budget
        case selectedWorkflowRevision = "selected_workflow_revision", previewObservationID = "preview_observation_id"
        case pendingActionID = "pending_action_id", pendingModelCallID = "pending_model_call_id", latestObservationIDs = "latest_observation_ids"
        case question, stopReason = "stop_reason", userAnswers = "user_answers", createdAt = "created_at", updatedAt = "updated_at"
    }
    var supported: Bool { schemaVersion == "a0.1" }
    var running: Bool { status == "running" }
    var resumable: Bool { supported && ["awaiting_input", "paused", "interrupted"].contains(status) }
    var cancellable: Bool { supported && ["running", "awaiting_input", "paused", "interrupted"].contains(status) }
    var terminal: Bool { ["blocked", "inconclusive", "failed", "cancelled", "draft_ready"].contains(status) }
    var awaitingInput: Bool { supported && status == "awaiting_input" }
    var pendingQuestion: String? { awaitingInput ? question : nil }
    var composerPlaceholder: String {
        guard supported else { return "Investigation status is unavailable." }
        if awaitingInput { return "Answer the agent’s question…" }
        if resumable { return "Add context before continuing the investigation…" }
        if terminal { return "Describe a new goal for this app…" }
        return "Describe what to detect and what should happen…"
    }
    var composerButtonTitle: String {
        if awaitingInput { return "Answer and continue" }
        if resumable { return "Continue investigation" }
        if terminal { return "Start new investigation" }
        return "Build my app"
    }
    var statusLabel: String {
        guard supported else { return "Unsupported investigation version" }
        if running, pendingModelCallID != nil { return "Agent choosing an action" }
        if running, stage == "workflow" { return "Constructing a workflow" }
        if status == "draft_ready" { return "Draft ready · review required" }
        return status.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
struct InvestigationDecision: Codable {
    let type: String, stateRevision: Int, decisionSummary: String
    let basedOnObservationIDs: [String]
    let action: [String: JSONValue]
    enum CodingKeys: String, CodingKey {
        case type, stateRevision = "state_revision", decisionSummary = "decision_summary"
        case basedOnObservationIDs = "based_on_observation_ids", action
    }
}
struct InvestigationActionRecord: Codable, Identifiable {
    let id: String, modelCallID: String
    let decision: InvestigationDecision
    let status: String, observationID: String?, startedAt: String, endedAt: String?
    enum CodingKeys: String, CodingKey {
        case id, modelCallID = "model_call_id", decision, status, observationID = "observation_id", startedAt = "started_at", endedAt = "ended_at"
    }
    var kind: String { decision.action["type"]?.string ?? "unknown" }
    var title: String { kind.replacingOccurrences(of: "_", with: " ").capitalized }
}
struct InvestigationObservation: Codable, Identifiable {
    let id: String, actionID: String, resultType: String, status: String
    let payload: [String: JSONValue]
    let error: JSONValue?
    let createdAt: String
    enum CodingKeys: String, CodingKey {
        case id, actionID = "action_id", resultType = "result_type", status, payload, error, createdAt = "created_at"
    }
    var items: [[String: JSONValue]] {
        guard case .array(let values) = payload["items"] else { return [] }
        return values.map(\.object)
    }
    var errorMessage: String? { error?.string ?? error?.object["message"]?.string }
    var summary: String {
        if errorMessage != nil {
            let action = resultType == "run_probe" ? "Vision probe" : resultType == "construct_workflow" ? "Workflow construction" : "Action"
            return "\(action) \(status == "interrupted" ? "interrupted" : status == "cancelled" ? "cancelled" : "failed")"
        }
        if let summary = payload["summary"]?.string { return summary }
        if let question = payload["question"]?.string { return question }
        if let counts = InvestigationPresentation.resultCounts(resultType: resultType, payload: payload) { return counts }
        if let name = payload["descriptor"]?.object["name"]?.string { return name }
        return "\(resultType.replacingOccurrences(of: "_", with: " ")) · \(status)"
    }
}
struct InvestigationSnapshot: Codable {
    var state: InvestigationState
    var actions: [InvestigationActionRecord]
    var observations: [InvestigationObservation]
    var statusLabel: String {
        state.status == "draft_ready" && selectedDraft == nil ? "Draft receipt unavailable" : state.statusLabel
    }
    func observation(for action: InvestigationActionRecord) -> InvestigationObservation? {
        observations.first { $0.id == action.observationID && $0.actionID == action.id }
    }
    func nextAction(after observation: InvestigationObservation) -> InvestigationActionRecord? {
        guard let index = actions.firstIndex(where: { $0.id == observation.actionID }) else { return nil }
        return actions.dropFirst(index + 1).first { $0.decision.basedOnObservationIDs.contains(observation.id) }
    }
    var selectedDraft: InvestigationDraftPreview? {
        guard state.supported, let revision = state.selectedWorkflowRevision, let observationID = state.previewObservationID,
              let observation = observations.first(where: { $0.id == observationID && $0.status == "completed" && $0.resultType == "construct_workflow" }),
              observation.payload["workflow_revision_id"]?.string == revision,
              observation.payload["validated"] == .bool(true), observation.payload["preview_success"] == .bool(true),
              let hash = observation.payload["spec_hash"]?.string, hash.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              observation.payload["preview_spec_hash"] == .string(hash),
              let action = actions.first(where: { $0.id == observation.actionID && $0.observationID == observationID && $0.status == "completed" && $0.kind == "construct_workflow" }),
              case .array(let media) = action.decision.action["media_ids"], (1...3).contains(media.count),
              media.allSatisfy({ $0.string?.isEmpty == false }), Set(media.compactMap(\.string)).count == media.count,
              observation.payload["preview_media_ids"] == .array(media),
              let preview: RunResult = InvestigationPresentation.decode(observation.payload["preview"]),
              !preview.frames.isEmpty, preview.frames.count == media.count else { return nil }
        return InvestigationDraftPreview(revisionID: revision, specHash: hash, observation: observation, action: action, preview: preview)
    }
}
struct InvestigationDraftPreview {
    let revisionID: String, specHash: String
    let observation: InvestigationObservation
    let action: InvestigationActionRecord
    let preview: RunResult
}
enum InvestigationPresentation {
    static func count(_ value: JSONValue) -> String {
        if case .number(let number) = value, number.isFinite, number >= 0, number.rounded() == number {
            return String(format: "%.0f", number)
        }
        return value.display
    }
    private static func itemCount(_ value: JSONValue?) -> Double? {
        guard case .number(let number) = value, number.isFinite, number >= 0, number.rounded() == number else { return nil }
        return number
    }
    private static func quantity(_ number: Double, singular: String, plural: String) -> String {
        "\(count(.number(number))) \(number == 1 ? singular : plural)"
    }
    static func resultCounts(resultType: String, payload: [String: JSONValue]) -> String? {
        let returned = itemCount(payload["returned_items"]), total = itemCount(payload["total_items"])
        var parts: [String] = []
        if let returned {
            let noun = resultType == "run_probe" ? "observation" : "result"
            parts.append(quantity(returned, singular: noun, plural: noun + "s") + " returned")
        }
        if let total {
            if resultType == "discover_capabilities", let query = payload["query"]?.string {
                let inventory = query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                parts.append(quantity(total, singular: inventory ? "catalog entry" : "metadata match", plural: inventory ? "catalog entries" : "metadata matches"))
            } else if returned == nil || returned != total {
                parts.append("\(count(.number(total))) total")
            }
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }
    static func shownValues(_ shown: Int, total: JSONValue?) -> String {
        let displayed = "Showing \(quantity(Double(shown), singular: "value", plural: "values"))."
        guard let total = itemCount(total) else { return displayed }
        return displayed + " Recorded total: \(count(.number(total)))."
    }
    static func sampleImageCount(_ count: Int) -> String {
        "\(count) sample \(count == 1 ? "image" : "images")"
    }
    static func decode<T: Decodable>(_ value: JSONValue?) -> T? {
        guard let value, let data = try? JSONEncoder().encode(value) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }
    static func accepts(_ incoming: InvestigationState, current: InvestigationState?, projectID: String, taskID: String) -> Bool {
        guard incoming.projectID == projectID, incoming.id == taskID else { return false }
        guard let current, current.id == incoming.id else { return true }
        return incoming.revision > current.revision || (incoming.revision == current.revision && incoming.updatedAt >= current.updatedAt)
    }
    static func resumeBody(_ state: InvestigationState, answer: String?) -> [String: JSONValue] {
        var body: [String: JSONValue] = ["expected_revision": .number(Double(state.revision))]
        if let answer, !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { body["answer"] = .string(answer) }
        return body
    }
    static func controlBody(_ state: InvestigationState, action: String) -> [String: JSONValue] {
        ["expected_revision": .number(Double(state.revision)), "action": .string(action)]
    }
    static func pretty(_ value: JSONValue) -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return (try? encoder.encode(value)).flatMap { String(data: $0, encoding: .utf8) } ?? ""
    }
}
