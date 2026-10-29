import SwiftUI

struct InvestigationHandoffCard: View {
    @EnvironmentObject var model: WorkspaceModel
    @ObservedObject var agent: AgentWorkspaceStore
    let openProposal: (Bool) -> Void
    @NativeState<Bool> private var discardConfirmation = false
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Continue to application review").font(.headline)
            if agent.handoffStatus?.status == "completed" {
                Text(agent.handoffStatus?.message ?? "This draft was imported for review. Its original investigation remains available in the application history.").font(.callout)
            } else if let snapshot = agent.investigation {
                if let reason = InvestigationHandoffPresentation.unavailability(snapshot, candidateCount: model.project?.candidates.count ?? 0) {
                    Text(reason).font(.callout).foregroundStyle(Studio.muted)
                } else {
                    if snapshot.state.status == "inconclusive" { Text("Investigation did not complete; this imports only its saved draft for review.").font(.callout).foregroundStyle(.orange) }
                    Text("Review the saved graph and its examples, then explicitly import it with project media as its source. Import runs a new development preview and pauses for your review.").font(.callout)
                    HStack {
                        Button(agent.handoffStatus?.proposal == nil ? (snapshot.state.status == "inconclusive" ? "Review saved draft recovery" : "Prepare review proposal") : "Review import proposal") { openProposal(false) }
                            .buttonStyle(.borderedProminent).disabled(model.busy || agent.handoffRequestPending || ["committing", "conflict"].contains(agent.handoffStatus?.status ?? ""))
                        if agent.handoffRequestPending || agent.handoffStatus?.status == "committing" { ProgressView().controlSize(.small) }
                    }
                }
            }
            if let message = agent.handoffStatus?.message, agent.handoffStatus?.status != "completed" { Text(message).font(.caption).foregroundStyle(Studio.muted) }
            if let error = agent.handoffError { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            if agent.handoffError != nil || ["committing", "interrupted", "conflict"].contains(agent.handoffStatus?.status ?? "") {
                Button("Check import status") {
                    guard let task = agent.investigationTaskID else { return }
                    model.perform("Checking import status") { try await agent.refreshHandoffStatus(taskID: task) }
                }.disabled(model.busy || agent.handoffRequestPending)
            }
            if agent.handoffStatus?.status == "interrupted" {
                Button("Prepare a new proposal") { openProposal(true) }.disabled(model.busy || agent.handoffRequestPending)
            }
            if agent.handoffStatus?.status == "conflict", agent.handoffStatus?.canAbort == true {
                Button("Discard incomplete import", role: .destructive) { discardConfirmation = true }.disabled(model.busy || agent.handoffRequestPending)
            }
            Text("Import does not establish quality or approve deployment. Annotation, evaluation, and approval gates still apply.").font(.caption).foregroundStyle(Studio.muted)
        }.panel()
        .confirmationDialog("Discard incomplete import?", isPresented: $discardConfirmation, titleVisibility: .visible) {
            Button("Discard incomplete import", role: .destructive) {
                model.perform("Discarding incomplete import") { try await agent.discardIncompleteHandoff() }
            }
            Button("Cancel", role: .cancel) { }
        } message: { Text("Discard only the partial import changes owned by this handoff. The saved investigation and its immutable evidence remain. A new proposal will require a separate review.") }
    }
}

struct InvestigationHandoffSheet: View {
    @EnvironmentObject var model: WorkspaceModel
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var agent: AgentWorkspaceStore
    let proposal: InvestigationHandoffProposal
    let snapshot: InvestigationSnapshot
    let onAccepted: (AgentBuildStatus) -> Void
    @NativeState<Bool> private var acknowledged = false
    private var matches: Bool { proposal.matches(snapshot) && agent.investigation.map(proposal.matches) == true }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Text("Import draft for review").font(.title2.weight(.semibold)); Spacer(); Button("Close") { dismiss() }.disabled(agent.handoffRequestPending) }
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(proposal.candidateName).font(.title3.weight(.medium))
                    if proposal.originTaskStatus == "inconclusive" {
                        Text("Investigation did not complete; this imports only its saved draft for review.").font(.callout.weight(.medium)).foregroundStyle(.orange)
                        if let reason = proposal.originStopReason { Text("Original stop reason: \(reason)").font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled) }
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Change the source to this app’s project media").font(.headline)
                        Text("Saved preview: \(InvestigationPresentation.sampleImageCount(proposal.originalMediaCount))\nProject media: \(InvestigationPresentation.sampleImageCount(proposal.projectMediaCount))").font(.callout)
                        Text("The saved graph and model bindings are preserved. The source changes from the frozen selected examples to project media. The engine validates the change and runs a new bounded preview before creating the review build.").font(.callout)
                        Text("\(proposal.sourceBefore) → \(proposal.sourceAfter)").font(.caption.monospaced()).textSelection(.enabled)
                        DisclosureGroup("Source and proposal identities") {
                            Text("Original spec: \(proposal.originalSpecHash)\nImported spec: \(proposal.candidateSpecHash)\nProposal: \(proposal.id)\nProposal hash: \(proposal.proposalHash)").font(.caption2.monospaced()).textSelection(.enabled)
                        }.font(.caption)
                    }.panel()
                    if matches, let draft = snapshot.selectedDraft {
                        graph(draft)
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Proposed evaluation assumption").font(.headline)
                            Text("\(proposal.metric) · target \(proposal.target.formatted(.number.precision(.fractionLength(0...6))))").font(.callout.monospaced())
                            Text("This is a proposed metric and target, not a measured result. Review the objective, labels, and evidence configuration before evaluation.").font(.caption).foregroundStyle(Studio.muted)
                        }.panel()
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Original selected-sample evidence").font(.headline)
                            Text("The preview below belongs to the saved investigation revision. The imported candidate receives its own new preview after acceptance.").font(.caption).foregroundStyle(Studio.muted)
                            InvestigationEvidenceView(snapshot: snapshot, selectedObservationID: .constant(draft.observation.id))
                        }
                    } else { Text("This proposal no longer matches the selected draft. Close it and refresh before importing.").foregroundStyle(.orange) }
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Review limits").font(.headline)
                        ForEach(proposal.limitations, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted) }
                        Text("A static crop remains static. Results on selected examples do not establish performance on different layouts. Import does not mark annotations reviewed or approve a recorded run.").font(.caption).foregroundStyle(Studio.muted)
                    }.panel()
                }.padding(.trailing, 8)
            }
            Divider()
            Toggle("I reviewed the source change and want this draft to use project media.", isOn: $acknowledged).font(.callout).disabled(agent.handoffRequestPending)
            if let error = agent.handoffError { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            HStack {
                if agent.handoffRequestPending { ProgressView().controlSize(.small); Text("Validating and previewing the imported candidate…").font(.caption) }
                Button("Refresh proposal") {
                    model.perform("Refreshing import proposal") { try await agent.prepareHandoff(refreshProposal: true) }
                }.disabled(model.busy || agent.handoffRequestPending || ["committing", "conflict"].contains(agent.handoffStatus?.status ?? ""))
                Spacer()
                Button("Import draft for review") {
                    model.perform("Importing draft for review") {
                        onAccepted(try await agent.acceptHandoff(proposal, acknowledged: acknowledged))
                    }
                }.buttonStyle(.borderedProminent).disabled(!acknowledged || !matches || model.busy || agent.handoffRequestPending || ["committing", "conflict"].contains(agent.handoffStatus?.status ?? ""))
            }
        }.padding(24).frame(width: 900, height: 760).interactiveDismissDisabled(agent.handoffRequestPending)
    }
    private func graph(_ draft: InvestigationDraftPreview) -> some View {
        let graph = draft.action.decision.action["graph"] ?? .object([:])
        let bindings = draft.observation.payload["model_bindings"] ?? .array([])
        return VStack(alignment: .leading, spacing: 8) {
            Text("Saved graph and model bindings").font(.headline)
            if case .array(let nodes) = graph.object["nodes"] {
                ForEach(Array(nodes.enumerated()), id: \.offset) { _, value in
                    let node = value.object
                    Text("\(node["id"]?.string ?? "node") · \(node["type"]?.string ?? "unknown")").font(.callout.monospaced())
                    if let input = node["image"]?.string { Text("Image input: \(input)").font(.caption).foregroundStyle(Studio.muted) }
                    if let capability = node["model_capability_id"]?.string { Text(capability).font(.caption).foregroundStyle(Studio.muted) }
                }
            }
            DisclosureGroup("Exact node parameters and connections") { Text(InvestigationPresentation.pretty(graph)).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption)
            DisclosureGroup("Captured model bindings") { Text(InvestigationPresentation.pretty(bindings)).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption)
        }.panel()
    }
}

struct InvestigationHistorySheet: View {
    @Environment(\.dismiss) private var dismiss
    let snapshot: InvestigationSnapshot
    @NativeState<String?> private var selectedObservationID: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Text("Investigation history").font(.title2.weight(.semibold)); Spacer(); Button("Close") { dismiss() } }
            Text("Original decisions, status, and evidence are retained separately from the imported candidate’s review and evaluation.").font(.caption).foregroundStyle(Studio.muted)
            HStack(alignment: .top, spacing: 20) {
                ScrollView { InvestigationActivityView(snapshot: snapshot, selectedObservationID: $selectedObservationID) }.frame(width: 340)
                Divider()
                ScrollView { InvestigationEvidenceView(snapshot: snapshot, selectedObservationID: $selectedObservationID) }.frame(maxWidth: .infinity)
            }
        }.padding(24).frame(width: 1000, height: 740)
    }
}
