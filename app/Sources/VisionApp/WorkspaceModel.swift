import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class WorkspaceModel: ObservableObject {
    @Published var projects: [Project] = []
    @Published var selectedID: String?
    @Published var project: Project?
    @Published var section = "Agent"
    @Published var capabilityFocus: String?
    @Published var busy = false
    @Published var activity = ""
    @Published var error: String?
    @Published var notice: String?
    @Published var prompt = ""
    @Published var selectedCandidate = 0
    @Published var previewIsPrevious = false
    @Published var previewIsRecorded = false
    @Published var previewCandidateIndex: Int?
    @Published var previewPipeline: Pipeline?
    @Published var previewRequestID: UUID?
    @Published var preview: RunResult? {
        didSet { previewIsPrevious = false; previewIsRecorded = false; previewCandidateIndex = nil; previewPipeline = nil; previewRequestID = nil }
    }
    var displayedPreviewPipeline: Pipeline? { previewPipeline ?? candidate }
    @Published var frameIndex = 0
    @Published var evaluation: Evaluation?
    @Published var dataset: EvalDataset?
    @Published var events: [EventRecord] = []
    @Published var reviews: [ReviewEntry] = []
    @Published var settings = AppSettings()
    @Published var models: [JSONValue] = []
    @Published var health: JSONValue?
    @Published var answer: AskResponse?
    @Published var trainingJob: TrainingJob?
    @Published var trainingProjectID: String?
    @Published var zones: [Zone] = []
    @Published var zonesConfirmed = false
    @Published var zonesOrigin = "unconfirmed"
    @Published var modelID = "owlv2-base-patch16"
    var lastAgentOutputKeys: [String: String] = [:]
    private var agentStores: [String: AgentWorkspaceStore] = [:]
    private var datasetStores: [String: DatasetWorkspace] = [:]
    lazy var liveCapture = LiveCaptureModel(client: client)
    let supervisor: EngineSupervisor
    var client: EngineClient { supervisor.client }
    var candidate: Pipeline? {
        guard let p = project, p.candidates.indices.contains(selectedCandidate) else { return nil }
        return p.candidates[selectedCandidate]
    }
    var frame: FrameResult? {
        guard let frames = preview?.frames, frames.indices.contains(frameIndex) else { return nil }
        return frames[frameIndex]
    }
    init(supervisor: EngineSupervisor) { self.supervisor = supervisor }
    func agentWorkspace(for projectID: String) -> AgentWorkspaceStore {
        if let store = agentStores[projectID] { return store }
        let store = AgentWorkspaceStore(projectID: projectID, client: client)
        agentStores[projectID] = store; return store
    }
    func datasetWorkspace(for projectID: String) -> DatasetWorkspace {
        if let existing = datasetStores[projectID] { return existing }
        let store = DatasetWorkspace(projectID: projectID, client: client)
        datasetStores[projectID] = store
        return store
    }
    var hasUnsavedAnnotations: Bool { datasetStores.values.contains { $0.isDirty || $0.saving } }
    func flushAnnotations() async -> Bool {
        for store in datasetStores.values where store.isDirty || store.saving {
            if !(await store.saveNow()) { selectedID = store.projectID; section = "Dataset"; error = store.error ?? "Save or discard the annotation draft before closing."; return false }
        }
        return true
    }
    func perform(_ message: String, work: @escaping () async throws -> Void) {
        guard !busy else { return }
        guard supervisor.connected else { error = supervisor.status; return }
        busy = true; activity = message; error = nil; notice = nil
        Task {
            defer { busy = false; activity = "" }
            do { try await work() } catch { self.error = error.localizedDescription }
        }
    }
    func start() async {
        busy = true; activity = "Connecting to local engine"
        defer { busy = false; activity = "" }
        await supervisor.start()
        guard supervisor.connected else { error = supervisor.status; return }
        do { try await refresh() } catch { self.error = error.localizedDescription }
    }
    func refresh() async throws {
        try await supervisor.validateConnection()
        projects = try await client.request("GET", "/projects")
        settings = try await client.request("GET", "/settings")
        models = try await client.request("GET", "/models")
        health = try await client.request("GET", "/health")
        supervisor.status = "Engine connected"
        if let id = selectedID { project = try await client.request("GET", "/projects/\(id)") }
    }
    func select(_ id: String?) {
        Task { await liveCapture.stop() }
        selectedID = id
        section = "Agent"
        preview = nil; evaluation = nil; frameIndex = 0; selectedCandidate = 0; zones = []; zonesConfirmed = false; zonesOrigin = "unconfirmed"; answer = nil
        guard let id else { project = nil; return }
        perform("Opening project") {
            self.project = try await self.client.request("GET", "/projects/\(id)")
            self.prompt = UserDefaults.standard.string(forKey: "vision.goalDraft.\(id)") ?? (self.project?.messages.isEmpty == true ? self.project?.brief ?? "" : "")
            self.modelID = self.project?.fixture == true ? "fixture-color-v1" : "owlv2-base-patch16"
            try await self.loadEvidence()
        }
    }
    func create(name: String, useCase: String = "custom", demo: Bool = false, goal: String = "") {
        perform(demo ? "Preparing synthetic walkthrough" : "Creating project") {
            let project: Project = try await self.client.request("POST", "/projects", body: ["name": .string(name), "use_case": .string(useCase)])
            self.selectedID = project.id; self.project = project; self.section = "Agent"
            self.prompt = goal; self.savePromptDraft()
            self.selectedCandidate = 0; self.preview = nil; self.evaluation = nil
            if demo {
                let _: JSONValue = try await self.client.request("POST", "/projects/\(project.id)/demo", body: [:])
                self.modelID = "fixture-color-v1"
                let response: PlanResponse = try await self.client.request("POST", "/projects/\(project.id)/plan", body: ["prompt": .string(self.prompt), "mode": .string("template"), "model": .string(self.modelID)])
                self.project = response.project
                self.preview = try await self.client.request("POST", "/projects/\(project.id)/preview", body: ["candidate_index": .number(0)])
            }
            try await self.refresh(); try await self.loadEvidence()
        }
    }
    func importMedia() {
        guard let id = selectedID else { return }
        let panel = NSOpenPanel()
        panel.canChooseFiles = true; panel.canChooseDirectories = true; panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.image, .movie, .folder]
        panel.message = "Choose representative images, a recorded clip, or an image folder for your goal."
        guard panel.runModal() == .OK else { return }
        perform("Importing media") {
            let _: JSONValue = try await self.client.request("POST", "/projects/\(id)/media", body: ["paths": .array(panel.urls.map { .string($0.path) })])
            try await self.refresh(); try await self.loadEvidence()
        }
    }
    func plan(mode: String) {
        guard let id = selectedID else { return }
        perform(mode == "agent" ? "Planning with your local model" : "Building a pipeline template") {
            let response: PlanResponse = try await self.client.request("POST", "/projects/\(id)/plan", body: ["prompt": .string(self.prompt), "mode": .string(mode), "model": .string(self.modelID)])
            self.project = response.project; self.selectedCandidate = 0; self.preview = nil; self.evaluation = nil
            self.notice = response.questions.isEmpty ? response.message : response.questions.joined(separator: "\n")
            try await self.refresh()
        }
    }
    func saveCandidate(_ pipeline: Pipeline, base: Pipeline, onSaved: @escaping (Pipeline) -> Void) {
        guard let id = selectedID else { return }
        let index = selectedCandidate
        perform("Validating workflow changes") {
            do {
                let updated = try await self.client.send("PUT", "/projects/\(id)/candidates/\(index)", value: CandidateUpdateRequest(spec: pipeline, baseSpec: base), as: Project.self)
                guard updated.candidates.indices.contains(index) else { throw EngineError.protocolError("The saved candidate is missing from the engine response.") }
                self.project = updated
                onSaved(updated.candidates[index])
                self.preview = nil; self.evaluation = nil; try await self.refresh()
                self.notice = "Workflow saved. Run a preview, then evaluate the edited candidate."
            } catch EngineError.server(409, let message) {
                self.project = try await self.client.request("GET", "/projects/\(id)")
                throw EngineError.server(409, message + " Your draft is preserved. Revert loads the latest saved workflow.")
            }
        }
    }
    func runPreview(candidateIndex: Int? = nil) {
        guard !busy, let id = selectedID, let project else { return }
        guard supervisor.connected else { error = supervisor.status; return }
        let index = candidateIndex ?? selectedCandidate
        guard project.candidates.indices.contains(index) else { return }
        let context = PreviewRequestContext(projectID: id, candidateIndex: index, pipeline: project.candidates[index])
        beginSamplePreview(context)
        perform("Running sample preview") {
            guard context.matches(project: self.project, selectedProjectID: self.selectedID, pendingID: self.previewRequestID) else { return }
            do {
                let result: RunResult = try await self.client.request("POST", "/projects/\(context.projectID)/preview", body: ["candidate_index": .number(Double(context.candidateIndex))])
                self.acceptSamplePreview(result, context: context)
            } catch {
                guard context.matches(project: self.project, selectedProjectID: self.selectedID, pendingID: self.previewRequestID) else { return }
                self.previewRequestID = nil
                throw error
            }
        }
    }
    func loadEvidence() async throws {
        guard let id = selectedID else { return }
        dataset = try await client.request("GET", "/projects/\(id)/annotations")
        events = try await client.request("GET", "/projects/\(id)/events")
        reviews = try await client.request("GET", "/projects/\(id)/review")
        do {
            let saved: ZonesResponse = try await client.request("GET", "/projects/\(id)/zones")
            zones = saved.zones; zonesConfirmed = saved.confirmed == true; zonesOrigin = saved.origin ?? "unconfirmed"
        } catch EngineError.server(404, _) { zones = []; zonesConfirmed = false; zonesOrigin = "unconfirmed" }
    }
    func resolveImagePath(_ path: String) -> String {
        if path.hasPrefix("/") { return path }
        return project?.media.first(where: { $0.hasSuffix("/" + path) }) ?? path
    }
    func saveAnnotations(onSaved: (() -> Void)? = nil) {
        guard let id = selectedID, let dataset else { return }
        perform("Saving reviewed labels") {
            let _: JSONValue = try await self.client.send("PUT", "/projects/\(id)/annotations", value: dataset, as: JSONValue.self)
            self.evaluation = nil; try await self.refresh(); self.notice = "Labels saved. Evaluate again to refresh deployment evidence."; onSaved?()
        }
    }
    func suggestLabels() {
        guard let id = selectedID else { return }
        perform("Suggesting labels with the selected detector") {
            self.dataset = try await self.client.request("POST", "/projects/\(id)/propose-labels", body: ["candidate_index": .number(Double(self.selectedCandidate)), "max_frames": .number(50)])
            self.evaluation = nil; try await self.refresh()
            self.notice = "Detector suggestions saved as unreviewed labels. Confirm or correct each image before evaluation; existing reviewed labels were preserved."
        }
    }
    func evaluate() {
        guard let id = selectedID else { return }
        perform("Evaluating candidate") {
            self.evaluation = try await self.client.request("POST", "/projects/\(id)/evaluate", body: ["candidate_index": .number(Double(self.selectedCandidate))])
            try await self.refresh()
        }
    }
    func approveDeployment(override: String?, scope: EvidenceApprovalScope = .promotion) {
        guard let id = selectedID else { return }
        let index = selectedCandidate
        perform("Recording deployment approval") {
            let request = EvidenceApprovalRequest(candidateIndex: index, approved: true, approvalScope: scope, overrideReason: override)
            let _: JSONValue = try await self.client.send("POST", "/projects/\(id)/deploy", value: request, as: JSONValue.self)
            try await self.refresh()
            let agent = self.agentWorkspace(for: id)
            await agent.refresh()
            if agent.build != nil {
                self.section = "Agent"
                self.applyBuild(try await agent.resume())
            } else { self.section = "Run" }
            self.notice = scope == .localTrial ? "Local trial approved; external alert delivery disabled." : "Quality promotion approved for the evaluated scope."
        }
    }
    func run() {
        guard let id = selectedID else { return }
        perform("Running approved pipeline") {
            self.preview = try await self.client.request("POST", "/projects/\(id)/run", body: ["candidate_index": .number(Double(self.selectedCandidate)), "max_frames": .number(50)])
            self.previewIsRecorded = true
            self.frameIndex = 0; try await self.refresh(); try await self.loadEvidence()
        }
    }
    func runOnNewMedia() {
        guard let id = selectedID else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = true; panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.image, .movie, .folder]
        panel.message = "Run the approved workflow on new media without changing your dataset or labels."
        guard panel.runModal() == .OK else { return }
        perform("Running approved workflow on new media") {
            self.preview = try await self.client.request("POST", "/projects/\(id)/run-on-media", body: ["candidate_index": .number(Double(self.selectedCandidate)), "paths": .array(panel.urls.map { .string($0.path) }), "max_frames": .number(50)])
            self.previewIsRecorded = true
            self.frameIndex = 0; try await self.refresh(); try await self.loadEvidence()
        }
    }
    func saveZones(continueBuilding: Bool = false) {
        guard let id = selectedID else { return }
        perform("Saving zones") {
            let data = try JSONEncoder().encode(self.zones)
            let json = try JSONDecoder().decode(JSONValue.self, from: data)
            let saved: ZonesResponse = try await self.client.request("PUT", "/projects/\(id)/zones", body: ["zones": json])
            self.zones = saved.zones; self.zonesConfirmed = saved.confirmed == true; self.zonesOrigin = saved.origin ?? "user"
            self.evaluation = nil; self.preview = nil; try await self.refresh()
            if continueBuilding {
                self.section = "Agent"
                self.applyBuild(try await self.agentWorkspace(for: id).resume())
            } else { self.notice = "Regions saved. The changed geometry requires a fresh evaluation." }
        }
    }
    func review(_ entry: ReviewEntry, status: String) {
        guard let id = selectedID else { return }
        perform("Updating review queue") {
            let _: JSONValue = try await self.client.request("POST", "/projects/\(id)/review/\(entry.id)", body: ["status": .string(status)])
            try await self.loadEvidence()
        }
    }
    func ask(_ question: String) {
        guard let id = selectedID else { return }
        perform("Finding event evidence") {
            self.answer = try await self.client.request("POST", "/projects/\(id)/ask", body: ["question": .string(question)])
        }
    }
    func saveSettings() {
        perform("Saving model settings") {
            self.settings = try await self.client.send("PUT", "/settings", value: self.settings, as: AppSettings.self)
            try await self.refresh(); self.notice = "Settings saved."
        }
    }
    var trainingAvailable: Bool { health?.object["capabilities"]?.object["training"] == .bool(true) }
    func startTraining(epochs: Int = 10, maxMinutes: Double = 2) {
        guard let id = selectedID else { return }
        perform("Starting approved local training") {
            self.trainingProjectID = id
            self.trainingJob = try await self.client.request("POST", "/projects/\(id)/train", body: ["candidate_index": .number(Double(self.selectedCandidate)), "max_minutes": .number(maxMinutes), "epochs": .number(Double(epochs)), "approved": .bool(true)])
            Task { await self.pollTraining(projectID: id) }
        }
    }
    private func pollTraining(projectID: String) async {
        guard let jobID = trainingJob?.id else { return }
        while let job = trainingJob, ["queued", "running"].contains(job.status) {
            try? await Task.sleep(for: .seconds(3))
            do {
                trainingJob = try await client.request("GET", "/projects/\(projectID)/jobs/\(jobID)")
                if trainingJob?.status == "completed" { try await refresh(); notice = "Training complete. Evaluate the new candidate before deployment." }
            } catch { self.error = "Training status unavailable: \(error.localizedDescription)"; break }
        }
    }
    func exportEvents() {
        guard let id = selectedID else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "vision-events.csv"; panel.allowedContentTypes = [.commaSeparatedText]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        perform("Exporting events") { try await self.client.rawRequest("GET", "/projects/\(id)/events.csv").write(to: url) }
    }
}
