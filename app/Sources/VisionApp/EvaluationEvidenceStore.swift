import Foundation

@MainActor final class EvaluationEvidenceStore: ObservableObject {
    let projectID: String
    let client: EngineClient
    let candidateIndex: Int
    @Published var draft: EvaluationConfiguration?
    @Published private(set) var saved: EvaluationConfiguration?
    @Published var selected: Set<String> = []
    @Published var search = ""
    @Published var roleFilter = "all"
    @Published private(set) var busy = false
    @Published private(set) var activity = ""
    @Published var conflict = false
    @Published var error: String?
    @Published var notice: String?
    @Published var acceptance: Evaluation?
    @Published var readiness: EvaluationReadiness?
    @Published private(set) var pendingReservationIDs: Set<String> = []
    var dirty: Bool { draft != saved }
    var images: [EvidenceImage] { draft?.images ?? [] }
    var selectedImages: [EvidenceImage] { images.filter { selected.contains($0.id) } }
    var visibleImages: [EvidenceImage] {
        images.filter { (roleFilter == "all" || $0.split == roleFilter) && (search.isEmpty || $0.filename.localizedCaseInsensitiveContains(search) || ($0.sceneGroup ?? "").localizedCaseInsensitiveContains(search)) }
    }
    private var route: String { "/projects/\(projectID)/evaluation" }
    init(projectID: String, client: EngineClient, candidateIndex: Int = 0) { self.projectID = projectID; self.client = client; self.candidateIndex = candidateIndex }
    func load(discardDraft: Bool = false) async {
        guard !busy, !dirty || discardDraft else { return }
        busy = true; activity = "Loading evaluation evidence"; error = nil; defer { busy = false }
        do {
            let configuration: EvaluationConfiguration = try await client.request("GET", route + "/config")
            draft = configuration; saved = configuration; conflict = false
            selected.formIntersection(Set(configuration.images.map(\.id)))
            await refreshReadiness()
        } catch { self.error = error.localizedDescription }
    }
    func assign(group: String?, split: String?, origin: String?) {
        guard !busy, !conflict, var value = draft else { return }
        for index in value.images.indices where selected.contains(value.images[index].id) {
            if let group { let normalized = group.trimmingCharacters(in: .whitespacesAndNewlines); value.images[index].sceneGroup = normalized.isEmpty ? nil : normalized }
            if let split { value.images[index].split = split }
            if let origin, value.images[index].dataOrigin != "synthetic" { value.images[index].dataOrigin = origin }
        }
        draft = value; notice = nil
    }
    @discardableResult func save() async -> Bool {
        guard !busy, !conflict, let value = draft else { return false }
        guard dirty else { return true }
        busy = true; activity = "Saving evidence configuration"; error = nil; notice = nil; defer { busy = false }
        do {
            let result = try await client.send("PUT", route + "/config", value: EvaluationConfigurationRequest(value), as: EvaluationConfiguration.self)
            draft = result; saved = result; acceptance = nil
            pendingReservationIDs = pendingReservationIDs.filter { id in result.images.first(where: { $0.id == id })?.split != "acceptance" }
            await refreshReadiness()
            notice = "Evidence configuration saved. Re-evaluate to measure this configuration. Annotation review flags are unchanged."
            return true
        } catch EngineError.server(409, let message) {
            conflict = true; error = message + " Your draft is preserved. Reload only when you are ready to discard these edits."; return false
        } catch { self.error = error.localizedDescription; return false }
    }
    @discardableResult func runAcceptance(candidateIndex: Int) async -> Evaluation? {
        guard !busy, !dirty, !conflict, readiness?.candidateIndex == candidateIndex, readiness?.acceptanceAvailable == true else { return nil }
        busy = true; activity = "Running the selected candidate’s acceptance test"; error = nil; notice = nil; defer { busy = false }
        do {
            let result: Evaluation = try await client.request("POST", route + "/acceptance", body: ["candidate_index": .number(Double(candidateIndex))])
            acceptance = result
            do {
                activity = "Refreshing evidence after acceptance"
                let configuration: EvaluationConfiguration = try await client.request("GET", route + "/config")
                draft = configuration; saved = configuration
            } catch { self.error = "Acceptance finished, but configuration refresh failed: \(error.localizedDescription)" }
            await refreshReadiness()
            return result
        } catch {
            let failure = error.localizedDescription
            // A failed response can still mean that reserved inputs were exposed.
            do {
                let configuration: EvaluationConfiguration = try await client.request("GET", route + "/config")
                draft = configuration; saved = configuration
            } catch { /* Readiness below still blocks another attempt if refresh fails. */ }
            await refreshReadiness()
            self.error = failure + (readiness == nil ? " Acceptance readiness could not be refreshed; retry is disabled." : "")
            return nil
        }
    }
    private func refreshReadiness() async {
        activity = "Checking acceptance eligibility"
        do {
            let value: EvaluationReadiness = try await client.request("GET", route + "/readiness?candidate_index=\(candidateIndex)")
            readiness = value
            acceptance = value.currentAcceptance
        } catch { readiness = nil; self.error = "Could not check acceptance readiness: \(error.localizedDescription)" }
    }
    /// Explicit import reserves the new rows before any preview or model suggestion.
    @discardableResult func importAcceptance(paths: [String]) async -> Bool {
        guard !busy, !dirty, !conflict, pendingReservationIDs.isEmpty, let current = saved, !paths.isEmpty else { return false }
        busy = true; activity = "Importing acceptance media without inference"; error = nil; notice = nil
        var imported = false
        defer { busy = false }
        do {
            let _: JSONValue = try await client.request("POST", "/projects/\(projectID)/media", body: ["paths": .array(paths.map(JSONValue.string))])
            imported = true
            let configuration: EvaluationConfiguration = try await client.request("GET", route + "/config")
            saved = configuration
            let previous = Set(current.images.map(\.id))
            selected = Set(configuration.images.map(\.id)).subtracting(previous)
            pendingReservationIDs = selected
            var reserved = configuration
            for index in reserved.images.indices where selected.contains(reserved.images[index].id) { reserved.images[index].split = "acceptance" }
            draft = reserved
            guard !selected.isEmpty else { notice = "No new image rows were returned. No acceptance assignments changed."; return true }
            activity = "Reserving the newly imported images"
            let result = try await client.send("PUT", route + "/config", value: EvaluationConfigurationRequest(reserved), as: EvaluationConfiguration.self)
            draft = result; saved = result; acceptance = nil
            pendingReservationIDs = []
            await refreshReadiness()
            notice = "\(selected.count) new images reserved for acceptance without model exposure. Declare their source groups and review their labels before testing."
            return true
        } catch EngineError.server(409, let message) {
            if imported { await recoverReservation(message: message, previous: Set(current.images.map(\.id))) }
            else { self.error = message }
        } catch {
            if imported { await recoverReservation(message: error.localizedDescription, previous: Set(current.images.map(\.id))) }
            else { self.error = error.localizedDescription }
        }
        return imported
    }
    private func recoverReservation(message: String, previous: Set<String>) async {
        activity = "Reloading configuration after reservation failed"
        conflict = true
        error = "\(message) Media was imported but reservation did not succeed. Do not import it again or run a preview."
        do {
            let current: EvaluationConfiguration = try await client.request("GET", route + "/config")
            saved = current
            if pendingReservationIDs.isEmpty { pendingReservationIDs = Set(current.images.map(\.id)).subtracting(previous) }
            draft = EvaluationReservation.rebase(current, newIDs: pendingReservationIDs); selected = pendingReservationIDs; conflict = false
            notice = "Current configuration reloaded. Newly imported images remain selected; save evidence configuration to finish reserving them."
            await refreshReadiness()
        } catch { self.error = "Media was imported but not reserved. Configuration refresh failed: \(error.localizedDescription). Reload to finish reservation; do not import the same media again." }
    }
}

enum EvaluationReservation {
    static func rebase(_ current: EvaluationConfiguration, newIDs: Set<String>) -> EvaluationConfiguration {
        var recovered = current
        for index in recovered.images.indices where newIDs.contains(recovered.images[index].id) { recovered.images[index].split = "acceptance" }
        return recovered
    }
}
