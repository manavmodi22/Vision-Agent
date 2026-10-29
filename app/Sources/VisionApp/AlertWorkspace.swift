import SwiftUI

@MainActor
final class AlertWorkspace: ObservableObject {
    @Published var draft = AlertConfiguration.empty
    @Published var saved: AlertConfiguration?
    @Published var deliveries: [AlertDelivery] = []
    @Published var secretChanges: [String: JSONValue] = [:]
    @Published var busy = false
    @Published var error: String?
    @Published var notice: String?
    let projectID: String
    let client: EngineClient
    init(projectID: String, client: EngineClient) { self.projectID = projectID; self.client = client }
    var route: String { "/projects/\(projectID)" }
    var isDirty: Bool { saved != nil && (draft != saved || !secretChanges.isEmpty) }
    var validationMessage: String? {
        if !(0...86400).contains(draft.minimumIntervalS) { return "Set the minimum interval between 0 and 86,400 seconds." }
        if draft.targets.count > 10 { return "A project supports up to 10 alert targets." }
        if draft.enabled && !draft.targets.contains(where: \.enabled) { return "Enable at least one target before enabling project alerts." }
        for target in draft.targets {
            if let problem = target.validationMessage { return "\(target.name.isEmpty ? target.kind.title : target.name): \(problem)" }
        }
        return nil
    }
    func load() async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        do {
            let configuration: AlertConfiguration = try await client.request("GET", route + "/alerts")
            let history: [AlertDelivery] = try await client.request("GET", route + "/alert-deliveries")
            saved = configuration; draft = configuration; deliveries = history; secretChanges = [:]
        } catch { self.error = error.localizedDescription }
    }
    func saveApproved() async {
        guard !busy, saved != nil else { return }
        guard validationMessage == nil else { error = validationMessage; return }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let request = AlertSaveRequest(configuration: draft, secrets: secretChanges)
            let _: JSONValue = try await client.send("PUT", route + "/alerts", value: request, as: JSONValue.self)
            // Clear credential material as soon as the accepted write completes.
            secretChanges = [:]
            let configuration: AlertConfiguration = try await client.request("GET", route + "/alerts")
            saved = configuration; draft = configuration
            deliveries = try await client.request("GET", route + "/alert-deliveries")
            notice = configuration.enabled ? "Alert configuration approved and enabled." : "Alert configuration saved. Project alerts are disabled."
        } catch { self.error = error.localizedDescription }
    }
    func testApproved(_ target: AlertTarget) async {
        guard !busy, let current = saved?.targets.first(where: { $0.id == target.id }), current == target else {
            error = "Refresh the saved target before sending a test."; return
        }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let delivery: AlertDelivery = try await client.request("POST", route + "/alerts/test", body: ["target_id": .string(target.id), "approved": .bool(true)])
            deliveries = try await client.request("GET", route + "/alert-deliveries")
            notice = "Generated test recorded as \(delivery.status.rawValue). Refresh delivery history to check its receipt."
        } catch { self.error = error.localizedDescription }
    }
    func retryApproved(_ delivery: AlertDelivery, target: AlertTarget) async {
        guard !busy, delivery.status.canRetry, saved?.targets.first(where: { $0.id == delivery.targetID }) == target else {
            error = "Only failed deliveries to a current saved target can be retried."; return
        }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let result: AlertDelivery = try await client.request("POST", route + "/alert-deliveries/\(delivery.id)/retry", body: ["approved": .bool(true)])
            deliveries = try await client.request("GET", route + "/alert-deliveries")
            notice = "Retry recorded as \(result.status.rawValue)."
        } catch { self.error = error.localizedDescription }
    }
    func refreshHistory() async {
        guard !busy else { return }
        busy = true; error = nil
        defer { busy = false }
        do { deliveries = try await client.request("GET", route + "/alert-deliveries") }
        catch { self.error = error.localizedDescription }
    }
    func update(_ target: AlertTarget, secret: JSONValue?) {
        if let index = draft.targets.firstIndex(where: { $0.id == target.id }) { draft.targets[index] = target }
        else { draft.targets.append(target) }
        secretChanges[target.id] = secret
    }
    func remove(_ target: AlertTarget) {
        draft.targets.removeAll { $0.id == target.id }
        secretChanges[target.id] = nil
    }
    func credentialSummary(_ target: AlertTarget) -> String {
        switch secretChanges[target.id] {
        case .null: return "Remove stored credential"
        case .string: return "Replace stored credential"
        default: return target.hasSecret ? "Preserve stored credential" : "No credential"
        }
    }
}
