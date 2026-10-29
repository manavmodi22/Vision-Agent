import SwiftUI

struct InvestigationActivityView: View {
    let snapshot: InvestigationSnapshot
    @Binding var selectedObservationID: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Your objective").font(.caption.weight(.semibold)).foregroundStyle(Studio.muted)
            Text(snapshot.state.objective).font(.callout).textSelection(.enabled)
            ForEach(Array(snapshot.state.userAnswers.enumerated()), id: \.offset) { _, answer in
                VStack(alignment: .leading, spacing: 4) { Text("Your answer").font(.caption).foregroundStyle(Studio.muted); Text(answer).font(.callout).textSelection(.enabled) }
            }
            HStack { Text("Experimental agent").font(.caption); Spacer(); Text(snapshot.statusLabel).font(.caption.weight(.medium)) }
            if let reason = snapshot.state.stopReason { Text(reason).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            let budget = snapshot.state.budget
            Text("Model calls \(budget.modelCalls)/\(budget.maxModelCalls) · actions \(budget.actions)/\(budget.maxActions) · probe attempts \(budget.probes)/\(budget.maxProbes) · \(Int(budget.elapsedS))/\(Int(budget.maxElapsedS)) s").font(.caption2).foregroundStyle(Studio.muted)
            ForEach(snapshot.actions) { action in
                VStack(alignment: .leading, spacing: 8) {
                    HStack { Text(action.title).font(.callout.weight(.semibold)); Spacer(); Text(action.status.capitalized).font(.caption).foregroundStyle(action.status == "failed" ? .orange : Studio.muted) }
                    Text(action.decision.decisionSummary).font(.callout).textSelection(.enabled)
                    if let observation = snapshot.observation(for: action) {
                        Text("Observed · \(observation.summary)").font(.caption).textSelection(.enabled)
                        Button("Inspect actual result") { selectedObservationID = observation.id }.font(.caption)
                        if let next = snapshot.nextAction(after: observation) {
                            Text("Next choice using this result · \(next.title)").font(.caption.weight(.medium))
                            Text(next.decision.decisionSummary).font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled)
                        }
                    } else if action.status == "reserved" { Text("Executing; no result recorded yet.").font(.caption).foregroundStyle(Studio.muted) }
                    DisclosureGroup("Recorded action") { Text(InvestigationPresentation.pretty(.object(action.decision.action))).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption2)
                }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8))
            }
            if snapshot.state.running, snapshot.state.pendingModelCallID != nil {
                HStack { ProgressView().controlSize(.small); Text("The agent is choosing its next action.").font(.caption).foregroundStyle(Studio.muted) }
            }
        }
    }
}

struct InvestigationControls: View {
    @EnvironmentObject var model: WorkspaceModel
    @ObservedObject var agent: AgentWorkspaceStore
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let error = agent.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            if let state = agent.investigation?.state {
                if let question = state.pendingQuestion { Text(question).font(.callout.weight(.medium)).textSelection(.enabled) }
                HStack {
                    if state.running, state.supported { Button("Pause") { model.controlInvestigation(agent, action: "pause") } }
                    if state.resumable, state.status != "awaiting_input" { Button("Resume") { model.resumeInvestigation(agent) } }
                    if state.cancellable { Button("Cancel investigation") { model.controlInvestigation(agent, action: "cancel") } }
                    Spacer()
                }.disabled(model.busy || agent.investigationRequestPending)
                if state.status == "interrupted" { Text("A previous call was interrupted. Resume lets the agent choose what to do next; it does not repeat that call automatically.").font(.caption2).foregroundStyle(Studio.muted) }
            }
        }
    }
}

struct InvestigationEvidenceView: View {
    @EnvironmentObject var supervisor: EngineSupervisor
    let snapshot: InvestigationSnapshot
    @Binding var selectedObservationID: String?
    @NativeState<Int> private var frameIndex = 0
    @NativeState<String?> private var selectedReadingID: String?
    @NativeState<Data?> private var imageData: Data?
    @NativeState<String?> private var imageError: String?
    @NativeState<[[String: JSONValue]]> private var probeItems = []
    private var draft: InvestigationDraftPreview? { snapshot.selectedDraft }
    private var observation: InvestigationObservation? {
        if let id = selectedObservationID, let match = snapshot.observations.first(where: { $0.id == id }) { return match }
        return draft?.observation ?? snapshot.observations.last(where: { $0.payload["image_artifact"] != nil }) ?? snapshot.observations.last
    }
    private var displayingDraft: Bool { draft != nil && observation?.id == draft?.observation.id }
    private var frame: FrameResult? {
        guard displayingDraft, let frames = draft?.preview.frames, frames.indices.contains(frameIndex) else { return nil }
        return frames[frameIndex]
    }
    private var imageReferences: [[String: JSONValue]] {
        guard let observation else { return [] }
        if let reference = observation.payload["image_artifact"]?.object, !reference.isEmpty { return [reference] }
        if case .array(let references) = observation.payload["artifact_refs"] {
            let images = references.map(\.object).filter { $0["mime_type"] == .string("image/png") }
            if !images.isEmpty { return images }
        }
        return observation.items.compactMap { $0["image_artifact"]?.object }.filter { !$0.isEmpty }
    }
    private var readings: [DisplayReading] { frame.map { ReadingPresentation.readings(ReadingPresentation.blocks($0)) } ?? InvestigationProbePresentation.readings(probeItems) }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            heading
            if let observation {
                HStack { Text(displayingDraft ? "Selected draft preview" : "Actual observation").font(.headline); Spacer(); Text(observation.status.capitalized).font(.caption).foregroundStyle(Studio.muted) }
                Text(observation.summary).font(.callout).textSelection(.enabled)
                if displayingDraft, let draft {
                    if draft.preview.frames.count > 1 {
                        Picker("Preview image", selection: $frameIndex) {
                            ForEach(Array(draft.preview.frames.enumerated()), id: \.offset) { index, value in Text(URL(fileURLWithPath: value.imagePath).lastPathComponent).tag(index) }
                        }
                    }
                    Text("Revision \(draft.revisionID)\nSpec \(draft.specHash)").font(.caption2.monospaced()).textSelection(.enabled).foregroundStyle(Studio.muted)
                }
                if displayingDraft || !imageReferences.isEmpty {
                    ImageCanvas(path: nil, imageData: imageData, detections: frame?.detections ?? (observation.payload["image_artifact"] != nil ? InvestigationProbePresentation.detections(probeItems) : []), readings: displayingDraft || observation.payload["image_artifact"] != nil ? readings : [], selectedReadingID: selectedReadingID, onReadingSelect: { selectedReadingID = $0 }, emptyTitle: "Observation image unavailable", emptyDetail: imageError ?? "Loading the exact recorded image…").frame(minHeight: 300, idealHeight: 390)
                    if imageReferences.count > 1 { Text("First of \(imageReferences.count) returned image artifacts. All references are in the recorded result.").font(.caption2).foregroundStyle(Studio.muted) }
                    if let imageError { Text(imageError).font(.caption).foregroundStyle(.orange) }
                }
                if let frame {
                    if !frame.counts.isEmpty { Text(frame.counts.keys.sorted().map { "\($0): \(frame.counts[$0]!)" }.joined(separator: " · ")).font(.callout).textSelection(.enabled) }
                    if !frame.texts.isEmpty {
                        Text("Workflow text output").font(.caption.weight(.semibold))
                        ForEach(Array(frame.texts.enumerated()), id: \.offset) { _, value in Text(value).font(.callout.monospaced()).textSelection(.enabled) }
                    }
                    ReadingEvidenceView(blocks: ReadingPresentation.blocks(frame), selectedID: $selectedReadingID)
                    if let comparisons = frame.comparisons, !comparisons.isEmpty { TextComparisonEvidence(comparisons: comparisons) }
                    Text("\(frame.detections.count) detections · \(String(format: "%.0f", frame.elapsedMs)) ms · preview events were not saved or dispatched").font(.caption2).foregroundStyle(Studio.muted)
                    ForEach(draft?.preview.warnings ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
                } else if !probeItems.isEmpty { probeValues }
                if case .array(let identities) = observation.payload["identity_refs"] {
                    DisclosureGroup("Executed model identity") { Text(InvestigationPresentation.pretty(.array(identities))).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption)
                }
                if observation.payload["pixels_visible_to_planner"] == .bool(false) { Text("These pixels were not supplied to the planner.").font(.caption2).foregroundStyle(Studio.muted) }
                if case .array(let limitations) = observation.payload["limitations"] { ForEach(Array(limitations.enumerated()), id: \.offset) { _, value in Text(value.string ?? "").font(.caption).foregroundStyle(Studio.muted) } }
                DisclosureGroup("Full recorded result") { Text(InvestigationPresentation.pretty(.object(observation.payload))).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption)
                if let error = observation.error {
                    DisclosureGroup("Error details") { Text(InvestigationPresentation.pretty(error)).font(.caption.monospaced()).foregroundStyle(.orange).textSelection(.enabled) }.font(.caption)
                }
            } else { EmptyCard(symbol: "viewfinder", title: "The investigation is starting", detail: "Actual observations and selected draft previews appear here as the agent executes its chosen actions.").frame(minHeight: 350) }
        }
        .task(id: "\(snapshot.state.id):\(observation?.id ?? ""):Frame\(frameIndex)") { await loadEvidence() }
        .onChange(of: observation?.id) { _, _ in frameIndex = 0; selectedReadingID = nil }
    }
    private var heading: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { Text("Investigation evidence").font(.headline); Spacer(); Text(snapshot.statusLabel).font(.caption).foregroundStyle(Studio.muted) }
            if let draft {
                Button("Show selected draft preview") { selectedObservationID = draft.observation.id; frameIndex = 0 }
                Text("This is the saved investigation preview. It does not establish measured quality or deployment approval.").font(.caption).foregroundStyle(Studio.muted)
            } else if snapshot.state.selectedWorkflowRevision != nil || snapshot.state.status == "draft_ready" {
                Text("The selected draft has no matching valid preview receipt. It cannot be presented as ready.").font(.caption).foregroundStyle(.orange)
            } else { Text("The agent can inspect examples and test vision capabilities before choosing a workflow.").font(.callout).foregroundStyle(Studio.muted) }
        }.panel()
    }
    private var probeValues: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Recorded values").font(.caption.weight(.semibold))
            Text(InvestigationPresentation.shownValues(probeItems.count, total: observation?.payload["total_items"])).font(.caption2).foregroundStyle(Studio.muted)
            ForEach(Array(probeItems.enumerated()), id: \.offset) { index, item in
                let reading = readings.first(where: { $0.index == index })
                VStack(alignment: .leading, spacing: 4) {
                    if let reading {
                        Button { selectedReadingID = reading.id } label: { HStack { Text("\(index + 1)").foregroundStyle(.cyan); Text(reading.observation.text.isEmpty ? "(empty value)" : reading.observation.text); Spacer() }.font(.callout.monospaced()) }.buttonStyle(.plain)
                        Text(reading.observation.symbology ?? reading.observation.kind).font(.caption2).foregroundStyle(Studio.muted)
                        if selectedReadingID == reading.id { Text(ReadingPresentation.codePoints(reading.observation.text)).font(.caption2.monospaced()).textSelection(.enabled) }
                    } else { Text(item["label"]?.string ?? item["item_id"]?.string ?? "Observation \(index + 1)").font(.callout) }
                    if item["text_truncated"] == .bool(true) { Text("This returned value was truncated by the server.").font(.caption2).foregroundStyle(.orange) }
                    DisclosureGroup("Value and geometry") { Text(InvestigationPresentation.pretty(.object(item))).font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption2)
                }.padding(8).background(selectedReadingID == reading?.id && reading != nil ? Color.cyan.opacity(0.1) : Studio.panel).clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }
    }
    private func loadEvidence() async {
        imageData = nil; imageError = nil; probeItems = []
        guard let observation else { return }
        let reader = InvestigationArtifacts(dataRoot: supervisor.dataRoot, projectID: snapshot.state.projectID, taskID: snapshot.state.id)
        let selectedFrame = frame, selectedDraft = displayingDraft ? draft : nil
        let imageReference = imageReferences.first
        let result = await Task.detached { () -> (Data?, [[String: JSONValue]], String?) in
            var items = observation.items
            do {
                if let selectedFrame, let selectedDraft { return (try reader.previewImage(selectedFrame, draft: selectedDraft), [], nil) }
                if let ref = observation.payload["result_artifact"]?.object, !ref.isEmpty {
                    let value = try JSONDecoder().decode(JSONValue.self, from: reader.artifact(ref, mime: "application/json"))
                    if case .array(let all) = value.object["items"] { items = Array(all.prefix(200)).map(\.object) }
                }
                if let ref = imageReference { return (try reader.artifact(ref, mime: "image/png"), items, nil) }
                return (nil, items, nil)
            } catch { return (nil, items, error.localizedDescription) }
        }.value
        guard !Task.isCancelled else { return }
        imageData = result.0; probeItems = result.1; imageError = result.2
    }
}
