import Foundation

enum CandidatePreviewChecks {
    @MainActor static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Candidate preview check failed: " + message) }; checks += 1
        }
        let first = Pipeline(name: "First", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "detector", type: "detect", params: ["model": .string("model-a")])])
        let second = Pipeline(name: "Second", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "detector", type: "detect", params: ["model": .string("model-b")])])
        let project = Project(id: "preview-project", name: "Comparison", useCase: "custom", status: "ready", createdAt: "now", updatedAt: "now", media: [], candidates: [first, second], evaluations: [], messages: [], synthetic: false, deploymentId: "approved-first")
        let model = WorkspaceModel(supervisor: EngineSupervisor()) // Construction only; never starts an engine.
        model.project = project; model.selectedID = project.id; model.selectedCandidate = 0
        model.preview = RunResult(frames: [], elapsedS: 1, warnings: ["older output"])
        model.previewIsRecorded = true; model.previewIsPrevious = true
        let secondRequest = PreviewRequestContext(projectID: project.id, candidateIndex: 1, pipeline: second)
        model.beginSamplePreview(secondRequest)
        try require(model.preview == nil && model.previewCandidateIndex == 1 && !model.previewIsRecorded && !model.previewIsPrevious, "switching inspection removes old boxes and recording state before inference")
        try require(model.selectedCandidate == 0 && model.project?.deploymentId == "approved-first", "inspection does not change approval candidate or deployment")
        let result = RunResult(frames: [], elapsedS: 2, warnings: ["actual second output"])
        try require(model.acceptSamplePreview(result, context: secondRequest) && model.preview?.elapsedS == 2 && model.displayedPreviewPipeline == second && !model.previewIsRecorded && !model.previewIsPrevious, "matching result retains its actual inspected pipeline and preview-only provenance")
        let newer = PreviewRequestContext(projectID: project.id, candidateIndex: 0, pipeline: first)
        model.beginSamplePreview(newer)
        try require(!model.acceptSamplePreview(result, context: secondRequest) && model.previewRequestID == newer.id && model.previewCandidateIndex == 0 && model.preview == nil, "late earlier candidate response cannot replace or clear the newer request")
        model.selectedID = "different-project"
        try require(!model.acceptSamplePreview(result, context: newer) && model.preview == nil, "late response from another project is discarded")
        model.selectedID = project.id; model.beginSamplePreview(newer)
        model.project?.candidates[0].blocks[0].params?["model"] = .string("changed-model")
        try require(!model.acceptSamplePreview(result, context: newer) && model.preview == nil, "same-index changed pipeline rejects stale inference")
        let missing = PreviewRequestContext(projectID: project.id, candidateIndex: 2, pipeline: first)
        model.beginSamplePreview(missing)
        try require(!model.acceptSamplePreview(result, context: missing), "removed candidate cannot receive stale output")
        try require(CandidatePreviewPresentation.label(index: 1, pipeline: second) == "Candidate 2 · model-b", "selector model label comes from the actual candidate graph")
        return checks
    }
}
