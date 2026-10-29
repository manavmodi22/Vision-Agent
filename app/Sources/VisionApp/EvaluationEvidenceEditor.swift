import SwiftUI
import UniformTypeIdentifiers

struct EvaluationEvidenceEditor: View {
    @EnvironmentObject var model: WorkspaceModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var store: EvaluationEvidenceStore
    let candidateIndex: Int
    let candidateName: String
    let onChanged: () async -> Void
    let onReview: () -> Void
    @NativeState<String> private var group = ""
    @NativeState<String> private var role = "validation"
    @NativeState<String> private var origin = "unknown"
    @NativeState<String> private var acceptanceGroups = ""
    @NativeState<Bool> private var discard = false
    init(projectID: String, client: EngineClient, candidateIndex: Int, candidateName: String, onChanged: @escaping () async -> Void, onReview: @escaping () -> Void) {
        _store = StateObject(wrappedValue: EvaluationEvidenceStore(projectID: projectID, client: client, candidateIndex: candidateIndex))
        self.candidateIndex = candidateIndex; self.candidateName = candidateName; self.onChanged = onChanged; self.onReview = onReview
    }
    private var editable: Bool { !store.busy && !store.conflict && model.supervisor.connected && model.selectedID == store.projectID && !model.busy && !model.agentWorkspace(for: store.projectID).running }
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Evaluation evidence").font(.title2.weight(.semibold))
                    Text("Keep related frames together. Reserve independent examples for one candidate’s acceptance test.").font(.caption).foregroundStyle(Studio.muted)
                }
                Spacer()
                Button("Back to conversation") { if store.dirty || !store.pendingReservationIDs.isEmpty { discard = true } else { dismiss() } }.disabled(store.busy)
            }.padding(20)
            Divider()
            HStack(spacing: 0) {
                imageList.frame(width: 320)
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        assignments
                        policy
                        acceptance
                    }.padding(20)
                }.frame(maxWidth: .infinity)
            }
            Divider()
            VStack(alignment: .leading, spacing: 8) {
                if let error = store.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                if let notice = store.notice { Text(notice).font(.caption).foregroundStyle(Studio.muted) }
                HStack {
                    if store.busy { ProgressView().controlSize(.small); Text(store.activity).font(.caption) }
                    else { Text(store.conflict ? "Conflict · draft preserved" : store.dirty ? "Unsaved configuration" : "Saved configuration").font(.caption).foregroundStyle(Studio.muted) }
                    Spacer()
                    Button("Refresh") { Task { await store.load() } }.disabled(store.busy || store.dirty || !model.supervisor.connected)
                    if store.conflict { Button("Discard draft & reload") { Task { await store.load(discardDraft: true) } } }
                    Button("Save evidence configuration") { Task { if await store.save() { await onChanged() } } }
                        .buttonStyle(.borderedProminent).disabled(!editable || !store.dirty)
                }
            }.padding(16)
        }.frame(width: 1040, height: 720).background(Studio.background)
            .task { await store.load() }
            .onChange(of: store.saved?.revision) { _, _ in acceptanceGroups = store.saved?.policy.requiredAcceptanceGroups.joined(separator: ", ") ?? "" }
            .interactiveDismissDisabled(store.dirty || store.busy || store.conflict || !store.pendingReservationIDs.isEmpty)
            .confirmationDialog(store.pendingReservationIDs.isEmpty ? "Discard unsaved evidence edits?" : "Imported images have not been reserved. Leave them unreserved?", isPresented: $discard) {
                Button(store.pendingReservationIDs.isEmpty ? "Discard edits" : "Leave images unreserved", role: .destructive) { dismiss() }; Button("Keep editing", role: .cancel) { }
            }
    }
    private var imageList: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Find image or group", text: $store.search).textFieldStyle(.roundedBorder)
            Picker("Show", selection: $store.roleFilter) {
                Text("All examples").tag("all")
                ForEach(["unassigned", "train", "validation", "acceptance"], id: \.self) { Text($0.capitalized).tag($0) }
            }
            HStack { Text("\(store.selected.count) selected").font(.caption); Spacer(); Button("Select visible") { store.selected = Set(store.visibleImages.map(\.id)) }; Button("Clear") { store.selected = [] } }.font(.caption2)
            Button("Add reserved acceptance media…", action: importAcceptance).font(.caption)
                .disabled(!editable || store.dirty || !store.pendingReservationIDs.isEmpty)
            ScrollView {
                LazyVStack(spacing: 6) {
                    ForEach(store.visibleImages) { image in
                        Button {
                            if store.selected.contains(image.id) { store.selected.remove(image.id) } else { store.selected.insert(image.id) }
                        } label: {
                            HStack(spacing: 9) {
                                Image(systemName: store.selected.contains(image.id) ? "checkmark.square.fill" : "square").foregroundStyle(Studio.accent)
                                ImageCanvas(path: EvaluationEvidencePresentation.imagePath(image.imagePath, projectMedia: model.project?.media ?? [])).frame(width: 60, height: 44)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(image.filename).lineLimit(1)
                                    Text(image.sceneGroup ?? "Unknown group").foregroundStyle(image.sceneGroup == nil ? .orange : Studio.muted).lineLimit(1)
                                    Text(image.split.capitalized).foregroundStyle(Studio.muted)
                                }.font(.caption2)
                                Spacer(minLength: 0)
                            }.padding(8).background(store.selected.contains(image.id) ? Studio.raised : Studio.panel).clipShape(RoundedRectangle(cornerRadius: 6))
                        }.buttonStyle(.plain)
                    }
                }
            }
        }.padding(14)
    }
    private var assignments: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Source and scene groups").font(.headline)
            Text("Use the same group for correlated frames from a scene. A different filename or a different frame from the same clip does not establish independence.").font(.caption).foregroundStyle(Studio.muted)
            HStack { TextField("Scene group for selected images", text: $group).textFieldStyle(.roundedBorder); Button("Assign group") { store.assign(group: group, split: nil, origin: nil) }.disabled(group.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || group.count > 120) }
            HStack {
                Picker("Role", selection: $role) { ForEach(["unassigned", "train", "validation", "acceptance"], id: \.self) { Text($0.capitalized).tag($0) } }
                Button("Assign role") { store.assign(group: nil, split: role, origin: nil) }
            }
            HStack {
                Picker("Origin", selection: $origin) { ForEach(["unknown", "real", "synthetic"], id: \.self) { Text($0.capitalized).tag($0) } }
                Button("Declare origin") { store.assign(group: nil, split: nil, origin: origin) }.disabled(store.selectedImages.contains(where: { $0.dataOrigin == "synthetic" }))
                Button("Clear group") { store.assign(group: "", split: nil, origin: nil) }
            }
            Text("Known synthetic data cannot be declared real. These edits do not change labels or their review state.").font(.caption2).foregroundStyle(Studio.muted)
            if store.selectedImages.count == 1, let image = store.selectedImages.first { sourceDetails(image) }
            else if !store.selected.isEmpty { Text("\(store.selectedImages.filter { !$0.exposureReasons.isEmpty }.count) selected images have recorded prior exposure. Select one image to inspect its source and reasons.").font(.caption).foregroundStyle(Studio.muted) }
        }.disabled(!editable || store.selected.isEmpty)
    }
    private func sourceDetails(_ image: EvidenceImage) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Recorded source · read only").font(.caption.weight(.semibold))
            Text("Source: \(image.sourceAssetID ?? "Unknown")\nOrigin: \(image.dataOrigin) · Group provenance: \(image.groupProvenance)").font(.caption).textSelection(.enabled)
            if let index = image.frameIndex { Text("Frame \(index)" + (image.timestampS.map { String(format: " · %.3f s", $0) } ?? "")).font(.caption2) }
            if let sha = image.sourceSHA256 { Text("SHA256 \(sha)").font(.caption2.monospaced()).textSelection(.enabled) }
            ForEach(image.exposureReasons, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            if image.exposureReasons.isEmpty { Text("No prior exposure is listed. The engine still checks separation and acceptance eligibility before testing.").font(.caption2).foregroundStyle(Studio.muted) }
        }.padding(10).frame(maxWidth: .infinity, alignment: .leading).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 7))
    }
    private var policy: some View {
        VStack(alignment: .leading, spacing: 11) {
            Text("Scope of the acceptance claim").font(.headline)
            policyField("Intended use", key: \.intendedUse, hint: "Where will the application be used, and for what decision?")
            policyField("Basis for independent groups", key: \.independentGroupBasis, hint: "Explain how these scenes are independent of development examples.")
            policyField("Coverage and limits", key: \.coverageRationale, hint: "Which conditions are covered, and which are still untested?")
            Text("Required acceptance groups").font(.caption.weight(.medium))
            TextField("Group names, separated by commas", text: $acceptanceGroups, axis: .vertical).textFieldStyle(.roundedBorder)
                .onChange(of: acceptanceGroups) { _, text in store.draft?.policy.requiredAcceptanceGroups = text.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } }
            Text("Declare the groups required for your intended use. A single held-out group supports only its stated scene scope; a group count alone does not establish representativeness.").font(.caption2).foregroundStyle(Studio.muted)
        }.disabled(!editable)
    }
    private func policyField(_ title: String, key: WritableKeyPath<EvaluationPolicy, String>, hint: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.caption.weight(.medium))
            TextField(hint, text: Binding(get: { store.draft?.policy[keyPath: key] ?? "" }, set: { store.draft?.policy[keyPath: key] = String($0.prefix(2000)) }), axis: .vertical).lineLimit(2...4).textFieldStyle(.roundedBorder)
        }
    }
    private var acceptance: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Test one selected candidate").font(.headline)
            Text("Candidate \(candidateIndex + 1) · \(candidateName)").font(.callout)
            Text("This is an acceptance test, not a comparison between models. It uses reserved groups once; later tuning or repeated evaluation cannot make already exposed images fresh again. The engine checks separation and eligibility before execution.").font(.caption).foregroundStyle(Studio.muted)
            Button("Review labels without running a model") { dismiss(); onReview() }.disabled(!editable || store.dirty)
            if store.dirty { Text("Save configuration changes to check current acceptance eligibility.").font(.caption).foregroundStyle(.orange) }
            else if let readiness = store.readiness {
                ForEach(readiness.acceptanceBlockers, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            } else { Text("Acceptance readiness has not been confirmed by the engine.").font(.caption).foregroundStyle(Studio.muted) }
            if store.readiness?.acceptanceReplayAvailable == true {
                Text("Captured acceptance is shown below. Viewing it runs no new inference.").font(.caption).foregroundStyle(Studio.muted)
            } else {
                Button("Run acceptance test for this candidate") {
                    Task { if await store.runAcceptance(candidateIndex: candidateIndex) != nil { await onChanged() } }
                }.buttonStyle(.borderedProminent).disabled(!editable || store.dirty || store.readiness?.acceptanceAvailable != true)
            }
            if let result = store.acceptance {
                Text("\(EvaluationPresentation.metricName(result.metric)): \(EvaluationPresentation.format(EvaluationPresentation.measuredValue(result), metric: result.metric)) · Target \(EvaluationPresentation.target(result)) · \(result.passed ? "met" : "missed")").font(.caption.monospaced())
                EvaluationQualityView(result: result)
            }
        }.panel()
    }
    private func importAcceptance() {
        guard editable, !store.dirty, store.pendingReservationIDs.isEmpty else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = true; panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.image, .movie, .folder]
        panel.message = "Add independent examples to reserve for acceptance. They remain unreviewed; no preview or model labeling is started."
        guard panel.runModal() == .OK else { return }
        guard editable else { return }
        let paths = panel.urls.map(\.path)
        Task { if await store.importAcceptance(paths: paths) { await onChanged() } }
    }
}
