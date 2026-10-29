import Foundation

struct AgentBuildLog: Decodable, Identifiable {
    let at: String
    let phase: String
    let message: String
    var id: String { "\(at)-\(phase)-\(message)" }
}
struct AgentBuildStatus: Decodable, Identifiable {
    let id: String
    let projectID: String
    let status: String
    let phase: String
    let nextAction: String
    let message: String
    let questions: [String]
    let log: [AgentBuildLog]
    let preview: RunResult?
    let selectedCandidateIndex: Int?
    let evaluations: [Evaluation]
    let acceptanceEvaluation: Evaluation?
    let project: Project
    let updatedAt: String
    let plan: PlatformBuildPlan?
    let execution: PlatformExecution?
    let toolEvents: [PlatformToolEvent]?
    enum CodingKeys: String, CodingKey {
        case id, projectID = "project_id", status, phase, nextAction = "next_action", message, questions, log, preview
        case selectedCandidateIndex = "selected_candidate_index", evaluations, project, updatedAt = "updated_at"
        case acceptanceEvaluation = "acceptance_evaluation"
        case plan, execution, toolEvents = "tool_events"
    }
    var running: Bool { status == "running" }
}

@MainActor
final class AgentWorkspaceStore: ObservableObject {
    let projectID: String
    let client: EngineClient
    @Published var build: AgentBuildStatus?
    @Published var error: String?
    @Published private(set) var submittedGoal: String?
    var running: Bool { build?.running == true }
    init(projectID: String, client: EngineClient) {
        self.projectID = projectID; self.client = client
        submittedGoal = UserDefaults.standard.string(forKey: "vision.submittedGoal.\(projectID)")
    }
    private func retainSubmission(_ prompt: String?) {
        submittedGoal = prompt
        UserDefaults.standard.set(prompt, forKey: "vision.submittedGoal.\(projectID)")
    }
    private func reconcileSubmission() {
        if let build, submittedGoal != nil, AgentConversation.pendingSubmission(submittedGoal, messages: build.project.messages) == nil { retainSubmission(nil) }
    }
    func refresh() async {
        do { build = try await client.request("GET", "/projects/\(projectID)/build"); reconcileSubmission(); error = nil }
        catch EngineError.server(404, _) { build = nil; error = nil }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }
    func start(prompt: String) async throws -> AgentBuildStatus {
        retainSubmission(prompt)
        let response: AgentBuildStatus = try await client.request("POST", "/projects/\(projectID)/build", body: ["prompt": .string(prompt)])
        build = response; reconcileSubmission(); error = nil; return response
    }
    func resume(action: String = "continue", prompt: String? = nil, trainingApproved: Bool = false) async throws -> AgentBuildStatus {
        var body: [String: JSONValue] = ["action": .string(action), "training_approved": .bool(trainingApproved)]
        if let prompt, !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { retainSubmission(prompt); body["prompt"] = .string(prompt) }
        let response: AgentBuildStatus = try await client.request("POST", "/projects/\(projectID)/build/continue", body: body)
        build = response; reconcileSubmission(); error = nil; return response
    }
}

/// Local echo is removed only after the matching human message is persisted.
enum AgentConversation {
    static func shouldShowStatus(_ message: String, messages: [ChatMessage]) -> Bool {
        func normalized(_ value: String) -> String { value.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }.joined(separator: " ") }
        let status = normalized(message)
        guard !status.isEmpty else { return false }
        guard let latestAssistant = messages.last(where: { $0.role == "assistant" }) else { return true }
        return !normalized(latestAssistant.content).contains(status)
    }
    static func phaseLabel(_ phase: String) -> String {
        switch phase {
        case "awaiting_zones": return "Waiting for regions"
        case "awaiting_media": return "Waiting for examples"
        case "awaiting_clarification": return "Waiting for your answer"
        case "awaiting_review": return "Waiting for review"
        case "configure_evaluation", "awaiting_evaluation_configuration": return "Waiting for evaluation evidence"
        case "awaiting_improvement": return "Waiting for an improvement choice"
        case "awaiting_approval", "awaiting_commit": return "Waiting for approval"
        default: return phase.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
    static func pendingSubmission(_ prompt: String?, messages: [ChatMessage]) -> String? {
        guard let prompt, !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        let normalized = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        return messages.contains { $0.role == "user" && $0.content.trimmingCharacters(in: .whitespacesAndNewlines) == normalized } ? nil : prompt
    }
}
