import Foundation

extension WorkspaceModel {
    func buildApp() {
        guard let id = selectedID else { return }
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let agent = agentWorkspace(for: id)
        perform("Starting your app build") {
            let response: AgentBuildStatus
            if agent.build?.nextAction == "answer_questions" { response = try await agent.resume(prompt: text) }
            else { response = try await agent.start(prompt: text) }
            self.applyBuild(response)
            self.prompt = ""; self.savePromptDraft()
        }
    }
    func createAndBuild(goal: String, paths: [String], sampleID: String? = nil) {
        let text = goal.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        perform("Creating your vision app") {
            let title = String(text.split(separator: "\n").first.map(String.init)?.prefix(60) ?? text.prefix(60))
            let project: Project = try await self.client.request("POST", "/projects", body: ["name": .string(title), "use_case": .string("custom")])
            self.selectedID = project.id; self.project = project; self.section = "Agent"
            self.selectedCandidate = 0; self.preview = nil; self.evaluation = nil; self.prompt = text
            self.savePromptDraft()
            if let sampleID {
                let _: Project = try await self.client.request("POST", "/projects/\(project.id)/samples/\(sampleID)/import", body: [:])
            }
            if !paths.isEmpty {
                let _: Project = try await self.client.request("POST", "/projects/\(project.id)/media", body: ["paths": .array(paths.map(JSONValue.string))])
            }
            try await self.refresh()
            self.applyBuild(try await self.agentWorkspace(for: project.id).start(prompt: text))
            self.prompt = ""; self.savePromptDraft()
        }
    }
    func continueBuild(action: String = "continue", trainingApproved: Bool = false) {
        guard let id = selectedID else { return }
        section = "Agent"
        let agent = agentWorkspace(for: id)
        perform("Continuing your app build") {
            guard await self.flushAnnotations() else { return }
            self.applyBuild(try await agent.resume(action: action, trainingApproved: trainingApproved))
        }
    }
    func returnToAgent() {
        guard let id = selectedID else { return }
        Task {
            guard await flushAnnotations() else { return }
            section = "Agent"
            let agent = agentWorkspace(for: id)
            await agent.refresh()
            if ["awaiting_review", "awaiting_approval", "awaiting_improvement"].contains(agent.build?.status ?? "") { continueBuild() }
        }
    }
    func applyBuild(_ build: AgentBuildStatus) {
        guard selectedID == build.projectID else { return }
        project = build.project
        let outputKey = build.id + ":" + build.updatedAt
        if lastAgentOutputKeys[build.projectID] != outputKey {
            lastAgentOutputKeys[build.projectID] = outputKey
            if let index = build.selectedCandidateIndex, build.project.candidates.indices.contains(index) { selectedCandidate = index }
            if let result = build.preview {
                preview = result; previewIsRecorded = build.status == "completed" && build.project.deploymentId != nil
                previewCandidateIndex = build.selectedCandidateIndex ?? selectedCandidate
                if let index = previewCandidateIndex, build.project.candidates.indices.contains(index) { previewPipeline = build.project.candidates[index] }
            }
            else if build.running, preview != nil { previewIsPrevious = true }
            else { preview = nil }
            frameIndex = min(frameIndex, max(0, (preview?.frames.count ?? 0) - 1))
            if let acceptance = build.acceptanceEvaluation { evaluation = acceptance }
            else if let index = build.selectedCandidateIndex, build.evaluations.indices.contains(index) { evaluation = build.evaluations[index] }
            else { evaluation = nil }
        }
        if let index = projects.firstIndex(where: { $0.id == build.projectID }) { projects[index] = build.project }
    }
    func openEvaluatedImage(_ path: String) {
        guard let id = selectedID else { return }
        perform("Opening evaluated image") {
            let store = self.datasetWorkspace(for: id)
            await store.load()
            if let error = store.error { throw EngineError.protocolError(error) }
            guard let image = EvaluationPresentation.exactImage(path: path, images: store.images) else {
                throw EngineError.protocolError("This evaluation image is no longer in the current dataset. Re-evaluate the current images before correcting it.")
            }
            store.search = ""; store.filter = .all
            await store.openImage(image.id)
            guard store.activeImageID == image.id else { throw EngineError.protocolError(store.error ?? "Could not open the evaluated image.") }
            self.section = "Dataset"
        }
    }
    func savePromptDraft() {
        guard let id = selectedID else { return }
        UserDefaults.standard.set(prompt, forKey: "vision.goalDraft.\(id)")
    }
}
