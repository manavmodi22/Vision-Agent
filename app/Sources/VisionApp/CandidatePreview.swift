import SwiftUI

struct PreviewRequestContext {
    let id = UUID()
    let projectID: String
    let candidateIndex: Int
    let pipeline: Pipeline
    func matches(project: Project?, selectedProjectID: String?, pendingID: UUID?) -> Bool {
        guard pendingID == id, selectedProjectID == projectID, let project,
              project.id == projectID, project.candidates.indices.contains(candidateIndex) else { return false }
        return project.candidates[candidateIndex] == pipeline
    }
}

enum CandidatePreviewPresentation {
    static func label(index: Int, pipeline: Pipeline) -> String {
        let models = pipeline.blocks.compactMap { $0.params?["model"]?.string }
        let names = Array(Set(models)).sorted()
        return "Candidate \(index + 1) · " + (names.isEmpty ? pipeline.name : names.joined(separator: ", "))
    }
}

extension WorkspaceModel {
    func beginSamplePreview(_ context: PreviewRequestContext) {
        preview = nil
        previewCandidateIndex = context.candidateIndex; previewPipeline = context.pipeline
        previewRequestID = context.id; frameIndex = 0
    }
    @discardableResult func acceptSamplePreview(_ result: RunResult, context: PreviewRequestContext) -> Bool {
        guard context.matches(project: project, selectedProjectID: selectedID, pendingID: previewRequestID) else {
            if previewRequestID == context.id { preview = nil }
            return false
        }
        preview = result
        previewCandidateIndex = context.candidateIndex; previewPipeline = context.pipeline
        previewIsRecorded = false; previewIsPrevious = false; frameIndex = 0
        return true
    }
}

struct CandidatePreviewPicker: View {
    @EnvironmentObject var model: WorkspaceModel
    let busy: Bool
    private var index: Int { model.previewCandidateIndex ?? model.selectedCandidate }
    var body: some View {
        if let candidates = model.project?.candidates, candidates.count > 1 {
            VStack(alignment: .leading, spacing: 6) {
                Picker("Inspect preview", selection: Binding(get: { index }, set: { model.runPreview(candidateIndex: $0) })) {
                    ForEach(Array(candidates.enumerated()), id: \.offset) { candidateIndex, pipeline in
                        Text(CandidatePreviewPresentation.label(index: candidateIndex, pipeline: pipeline)).tag(candidateIndex)
                    }
                }.disabled(busy || !model.supervisor.connected)
                Text("Preview inspection only · app approval is unchanged.").font(.caption2).foregroundStyle(Studio.muted)
            }
        }
    }
}
