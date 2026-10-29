import SwiftUI

struct BuildView: View {
    @EnvironmentObject var model: WorkspaceModel
    @StateObject private var agent: AgentWorkspaceStore
    @StateObject private var reviewStore: DatasetWorkspace
    @NativeState<String> private var artifactTab = "Preview"
    @NativeState<Bool> private var trainingApproval = false
    @NativeState<Bool> private var deploymentApproval = false
    @NativeState<Bool> private var annotationReview = false
    @NativeState<Bool> private var evidenceEditor = false
    @NativeState<Int> private var evidenceCandidate = 0
    @NativeState<String> private var evidenceCandidateName = ""
    @NativeState<Bool> private var reviewAfterEvidence = false
    init(store: AgentWorkspaceStore, dataset: DatasetWorkspace) {
        _agent = StateObject(wrappedValue: store); _reviewStore = StateObject(wrappedValue: dataset)
    }
    private var messages: [ChatMessage] { model.project?.messages ?? [] }
    private var working: Bool { model.busy || agent.running }
    private var pendingGoal: String? { AgentConversation.pendingSubmission(agent.submittedGoal, messages: messages) }
    private var hasStarted: Bool { working || agent.build != nil || pendingGoal != nil || !messages.isEmpty }
    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Text(hasStarted ? "Build with your agent" : "What should your app do?").font(.title3.weight(.semibold))
                        media
                        if let plan = agent.build?.plan { AgentPlanCard(plan: plan, execution: agent.build?.execution) }
                        conversation
                        if agent.build != nil { AgentTimelineView(agent: agent) }
                        DisclosureGroup("Build status history") { AgentWorkLog(agent: agent).padding(.top, 10) }.font(.caption).foregroundStyle(Studio.muted)
                    }.padding(24)
                }
                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    nextStep
                    composer
                }.padding(18).background(Studio.background)
            }.frame(minWidth: 340, idealWidth: 410, maxWidth: 460)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    application
                    if model.candidate != nil {
                        Picker("Application view", selection: $artifactTab) { Text("Preview").tag("Preview"); Text("Workflow details").tag("Workflow") }.pickerStyle(.segmented)
                    }
                    if artifactTab == "Workflow", model.candidate != nil {
                        Text("Workflow candidate \(model.selectedCandidate + 1)").font(.caption).foregroundStyle(Studio.muted)
                        PipelineInspector()
                        Button("Open workflow tools") { model.section = "Workflow" }.font(.caption)
                    } else {
                        CandidatePreviewPicker(busy: working)
                        PreviewPanel(agentContext: true, agentBuilding: working).frame(minHeight: 390)
                        if let path = model.frame?.imagePath, EvaluationPresentation.exactImage(path: path, images: reviewStore.images) != nil {
                            HStack { Button("Correct this image") { openReview(imagePath: path) }.disabled(working || reviewStore.loading); Text("Review labels for the displayed example.").font(.caption).foregroundStyle(Studio.muted); Spacer() }
                        }
                        if let warnings = model.preview?.warnings { ForEach(warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) } }
                        if let build = agent.build, !build.evaluations.isEmpty {
                            AgentEvaluationProof(build: build, busy: working || reviewStore.loading, approve: { deploymentApproval = true }, train: { trainingApproval = true }, correctImage: { openReview(imagePath: $0) }, reviewAnnotations: { openReview() }, editEvidence: { openEvidence() })
                        }
                    }
                }.padding(24)
            }.frame(maxWidth: .infinity)
        }
        .task(id: agent.projectID) {
            while !Task.isCancelled {
                await agent.refresh()
                if let build = agent.build { model.applyBuild(build) }
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
            }
        }
        .task(id: model.frame?.imagePath) { if model.frame != nil { await reviewStore.load() } }
        .sheet(isPresented: $annotationReview) { AgentAnnotationReview(store: reviewStore) }
        .sheet(isPresented: $evidenceEditor, onDismiss: { if reviewAfterEvidence { reviewAfterEvidence = false; openReview() } }) {
            EvaluationEvidenceEditor(projectID: agent.projectID, client: model.client, candidateIndex: evidenceCandidate, candidateName: evidenceCandidateName, onChanged: {
                try? await model.refresh()
                await agent.refresh()
                if let build = agent.build { model.applyBuild(build) }
                await reviewStore.load()
            }, onReview: { reviewAfterEvidence = true; evidenceEditor = false })
        }
        .sheet(isPresented: $deploymentApproval) { DeploymentApprovalSheet { deploymentApproval = false } }
        .sheet(isPresented: $trainingApproval) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Allow local detector training?").font(.title2.weight(.semibold))
                Text("The agent will train on reviewed examples, keep validation images held out, and evaluate the new candidate. This attempt is capped at two minutes. The build permits at most two training attempts and re-evaluates on held-out reviewed images. It does not approve deployment.").font(.callout)
                HStack { Button("Cancel") { trainingApproval = false }; Spacer(); Button("Allow training and continue") { trainingApproval = false; model.continueBuild(action: "improve", trainingApproved: true) }.buttonStyle(.borderedProminent) }
            }.padding(28).frame(width: 470)
        }
    }
    private var media: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack { Text("Your examples").font(.caption.weight(.medium)).foregroundStyle(Studio.muted); Spacer(); Button { model.importMedia() } label: { Label("Add media", systemImage: "plus") }.disabled(working) }
            if let images = model.project?.media, !images.isEmpty {
                ScrollView(.horizontal) { HStack(spacing: 8) { ForEach(Array(images.prefix(5).enumerated()), id: \.offset) { _, path in ImageCanvas(path: path).frame(width: 86, height: 59) } } }
                Text("\(images.count) sample images").font(.caption2).foregroundStyle(Studio.muted)
            } else { Text("Add photos or a short clip so the agent can test your goal.").font(.callout).foregroundStyle(Studio.muted) }
        }
    }
    private var conversation: some View {
        VStack(alignment: .leading, spacing: 14) {
            ForEach(Array(messages.enumerated()), id: \.offset) { _, message in
                messageBubble(message.role == "user" ? "You" : "Agent", text: message.content)
            }
            if let pendingGoal { messageBubble("You", text: pendingGoal) }
            if let build = agent.build, AgentConversation.shouldShowStatus(build.message, messages: messages) { messageBubble("Agent", text: build.message) }
            if let build = agent.build, !build.questions.isEmpty {
                ForEach(build.questions, id: \.self) { Text($0).font(.callout).textSelection(.enabled) }
            }
        }
    }
    private func messageBubble(_ role: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(role).font(.caption.weight(.semibold)).foregroundStyle(role == "You" ? Studio.muted : Studio.accent)
            Text(text).font(.callout).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(role == "You" ? Studio.raised.opacity(0.5) : Studio.panel).clipShape(RoundedRectangle(cornerRadius: 9))
    }
    @ViewBuilder private var nextStep: some View {
        if let build = agent.build, !build.running {
            switch build.nextAction {
            case "attach_media":
                HStack { Button("Add media") { model.importMedia() }; Button("Continue building") { model.continueBuild() }.buttonStyle(.borderedProminent).disabled(model.project?.media.isEmpty != false) }
            case "define_zones":
                Button("Mark regions") { model.section = "Zones" }.buttonStyle(.borderedProminent)
            case "review_labels":
                VStack(alignment: .leading, spacing: 10) {
                    Text("Your review is needed").font(.callout.weight(.semibold))
                    Text(EvaluationPresentation.isReading(model.candidate) ? "Check expected text or barcode values against each image. Only mark it reviewed after checking." : "Check the proposed boxes and classes on real examples. Only mark an image reviewed after checking it.").font(.caption).foregroundStyle(Studio.muted)
                    HStack { Button("Review annotations") { openReview() }.buttonStyle(.borderedProminent).disabled(reviewStore.loading); Button("Continue after review") { model.continueBuild() } }
                }.panel()
            case "approve_deployment":
                Button("Review results & approve app") { deploymentApproval = true }.buttonStyle(.borderedProminent)
            case "configure_evaluation":
                VStack(alignment: .leading, spacing: 8) {
                    Text("Choose how to establish evidence for this application.").font(.caption).foregroundStyle(Studio.muted)
                    HStack { Button("Edit evaluation evidence") { openEvidence() }.buttonStyle(.borderedProminent); Button("Review local trial") { deploymentApproval = true } }
                    Button("Re-evaluate") { model.continueBuild() }.disabled(working || !model.supervisor.connected)
                }
            case "approve_training":
                Button("Review training request") { trainingApproval = true }.buttonStyle(.borderedProminent)
            case "retry":
                Button("Retry build") { model.continueBuild() }.disabled(working)
            default: EmptyView()
            }
        }
    }
    private func openReview(imagePath: String? = nil) {
        model.perform("Opening example review") {
            await reviewStore.load()
            if let error = reviewStore.error { throw EngineError.protocolError(error) }
            reviewStore.search = ""; reviewStore.filter = .all
            if let image = AgentReviewContext.preferredImage(path: imagePath, images: reviewStore.images) {
                await reviewStore.openImage(image.id)
                guard reviewStore.activeImageID == image.id else { throw EngineError.protocolError(reviewStore.error ?? "Could not open the selected example.") }
            } else if imagePath != nil { throw EngineError.protocolError("This preview image is no longer in the dataset. Refresh the examples before reviewing it.") }
            annotationReview = true
        }
    }
    private func openEvidence() {
        guard !working, let candidate = model.candidate else { return }
        model.perform("Opening evaluation evidence") {
            guard await reviewStore.saveNow() else { throw EngineError.protocolError(reviewStore.error ?? "Save annotation changes before editing evaluation evidence.") }
            evidenceCandidate = model.selectedCandidate; evidenceCandidateName = candidate.name; evidenceEditor = true
        }
    }
    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            ZStack(alignment: .topLeading) {
                if model.prompt.isEmpty { Text(hasStarted ? "Answer the agent or describe what to change…" : "Describe what to detect and what should happen…").font(.callout).foregroundStyle(Studio.muted).padding(14).allowsHitTesting(false) }
                TextEditor(text: $model.prompt).font(.callout).scrollContentBackground(.hidden).padding(8).frame(height: 90)
            }.background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 9))
            HStack {
                if working { ProgressView().controlSize(.small); Text(agent.running ? agent.build.map { AgentConversation.phaseLabel($0.phase) } ?? "Working" : model.activity).font(.caption).foregroundStyle(Studio.muted).lineLimit(2) }
                Spacer()
                Button(messages.isEmpty && agent.build == nil ? "Build my app" : "Continue building") { model.buildApp() }
                    .buttonStyle(.borderedProminent).disabled(working || model.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }
    private var application: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("Your application").font(.headline); Spacer(); if model.project?.deploymentId != nil { StatusPill(text: EvidenceApprovalPresentation.projectStatus(model.project)) } else if model.candidate != nil { StatusPill(text: "Draft", color: Studio.muted) } }
            if model.project?.approvalScope == "local_trial" {
                Text("Local trial; external alert delivery disabled. Quality promotion has not been established.").font(.caption).foregroundStyle(.orange)
                ForEach(EvidenceApprovalPresentation.trialLimits(model.project), id: \.self) { Text($0).font(.caption2).foregroundStyle(Studio.muted) }
            }
            if let candidate = model.candidate {
                Text(model.project?.messages.first(where: { $0.role == "user" })?.content ?? model.project?.name ?? candidate.name).font(.title3.weight(.medium))
                HStack {
                    Text("Preview on your examples").font(.caption).foregroundStyle(Studio.muted)
                    Spacer()
                    if model.project?.deploymentId != nil { Button("Open app") { model.section = "Run" }.buttonStyle(.borderedProminent) }
                    else { Button("Test preview") { model.runPreview(candidateIndex: model.previewCandidateIndex) }.disabled(working) }
                }
            } else { Text("The agent's application and actual test results appear here as it builds.").font(.callout).foregroundStyle(Studio.muted) }
        }.panel()
    }
}
