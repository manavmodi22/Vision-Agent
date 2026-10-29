import SwiftUI

enum AgentReviewContext {
    static func preferredImage(path: String?, images: [DatasetImage]) -> DatasetImage? {
        if let path { return EvaluationPresentation.exactImage(path: path, images: images) }
        return images.first(where: { !$0.reviewed }) ?? images.first
    }
}

/// Reuses the persistent annotation workspace without navigating away from Agent.
struct AgentAnnotationReview: View {
    @EnvironmentObject var workspace: WorkspaceModel
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var store: DatasetWorkspace
    @NativeState<Bool> private var closing = false
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Review examples").font(.title2.weight(.semibold))
                    Text(workspace.project?.name ?? "Your application").font(.caption).foregroundStyle(Studio.muted).lineLimit(2)
                }
                Spacer()
                Button("Back to conversation") { finish(resume: false) }.disabled(closing || store.saving)
            }.padding(20)
            Divider()
            DatasetStudio(store: store, onContinue: { finish(resume: true) })
        }.frame(width: 1040, height: 680).background(Studio.background)
            .interactiveDismissDisabled(store.isDirty || store.saving || store.hasConflict || closing)
    }
    private func finish(resume: Bool) {
        guard !closing else { return }; closing = true
        Task {
            defer { closing = false }
            guard await store.saveNow() else { return }
            dismiss()
            if resume { workspace.returnToAgent() }
        }
    }
}
