import SwiftUI

struct RunView: View {
    @EnvironmentObject var model: WorkspaceModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    VStack(alignment: .leading, spacing: 6) { Eyebrow(text: "04 / Run"); Text("Run the approved pipeline locally.").font(.title3.weight(.medium)) }
                    Spacer()
                    Button("Run on new media…") { model.runOnNewMedia() }.buttonStyle(.borderedProminent).disabled(model.project?.deploymentId == nil || model.busy)
                    Button { model.run() } label: { Label("Run project images", systemImage: "play.fill") }.buttonStyle(.borderedProminent).disabled(model.project?.deploymentId == nil || model.busy)
                }
                if model.project?.deploymentId == nil {
                    HStack { Image(systemName: "lock.shield").foregroundStyle(.orange); Text("Evaluate a candidate and approve its deployment to enable runs.").font(.callout); Spacer(); Button("Go to Evaluate") { model.section = "Evaluate" } }.panel()
                } else { StatusPill(text: "Deployment approved") }
                if let project = model.project { LiveCaptureView(live: model.liveCapture, project: project, candidateIndex: model.selectedCandidate) }
                Text("Latest media run").font(.headline)
                PreviewPanel().frame(minHeight: 350)
                HStack(spacing: 16) {
                    MetricCard(title: "Frames", value: "\(model.preview?.frames.count ?? 0)", caption: "In the latest run")
                    MetricCard(title: "Elapsed", value: model.preview.map { String(format: "%.2f s", $0.elapsedS) } ?? "—", caption: "Measured pipeline time")
                    MetricCard(title: "Stored events", value: "\(model.events.count)", caption: "Local evidence records")
                }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }
    }
}

struct EventsView: View {
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<String> private var question = "How many pallets were detected?"
    @NativeState<String> private var filter = ""
    var filtered: [EventRecord] { model.events.filter { filter.isEmpty || $0.label.localizedCaseInsensitiveContains(filter) || $0.createdAt.contains(filter) } }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack { TextField("Filter by label or date", text: $filter).textFieldStyle(.roundedBorder).frame(maxWidth: 350); Spacer(); Button("Refresh") { model.perform("Refreshing evidence") { try await model.loadEvidence() } }; Button("Export CSV…") { model.exportEvents() }.disabled(model.events.isEmpty) }
                VStack(alignment: .leading, spacing: 12) {
                    Eyebrow(text: "Ask with evidence")
                    HStack { TextField("Ask about this project's events", text: $question).textFieldStyle(.roundedBorder).onSubmit { model.ask(question) }; Button("Ask") { model.ask(question) }.buttonStyle(.borderedProminent).disabled(model.busy || question.isEmpty) }
                    if let answer = model.answer {
                        Text(answer.answer).font(.callout).textSelection(.enabled)
                        Text("\(answer.evidence.count) supporting event records").font(.caption).foregroundStyle(Studio.muted)
                        ScrollView(.horizontal) { HStack { ForEach(answer.evidence.prefix(8)) { event in eventCard(event).frame(width: 200) } } }
                    }
                }.panel()
                if filtered.isEmpty { EmptyCard(symbol: "clock.arrow.circlepath", title: "Evidence appears here", detail: "Run an approved pipeline to create local events and crops. Each answer links back to stored evidence.").frame(height: 300) }
                else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: 16)], spacing: 16) { ForEach(filtered) { eventCard($0) } }
                }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }
    }
    private func eventCard(_ event: EventRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            ImageCanvas(path: event.cropPath ?? event.imagePath).frame(height: 150)
            HStack { Text(event.label).font(.headline); Spacer(); if let confidence = event.confidence { Text(String(format: "%.0f%%", confidence*100)).font(.caption.monospaced()).foregroundStyle(Studio.accent) } }
            Text(event.createdAt).font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted)
            if let counts = event.counts, !counts.isEmpty { Text(counts.keys.sorted().map { "\($0): \(counts[$0] ?? 0)" }.joined(separator: " · ")).font(.caption) }
            Button("Show evidence in Finder") { if let path = event.cropPath ?? event.imagePath { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) } }.font(.caption).buttonStyle(.plain).foregroundStyle(Studio.accent)
        }.panel()
    }
}

struct ReviewView: View {
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<Bool> private var trainingApproval = false
    @NativeState<Int> private var trainingEpochs = 10
    @NativeState<Double> private var trainingMinutes = 2
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack { VStack(alignment: .leading, spacing: 6) { Eyebrow(text: "05 / Improve"); Text("Inspect the uncertain frames.").font(.title3.weight(.medium)) }; Spacer(); Button("Refresh") { model.perform("Refreshing review queue") { try await model.loadEvidence() } } }
                HStack {
                    Text("Accept frames, correct their labels, then train a new local candidate.").font(.callout).foregroundStyle(Studio.muted)
                    Spacer()
                    Button("Train local detector") { trainingApproval = true }.buttonStyle(.borderedProminent).disabled(!model.trainingAvailable || model.candidate == nil || model.busy || ["queued", "running"].contains(model.trainingJob?.status ?? ""))
                }
                if !model.trainingAvailable { Text("A local training backend is not available. Check engine capabilities in Settings.").font(.caption).foregroundStyle(Studio.muted) }
                if let job = model.trainingJob, model.trainingProjectID == model.selectedID {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack { StatusPill(text: job.status, color: job.status == "failed" ? .orange : Studio.accent); Text(job.message ?? "Local training job").font(.callout) }
                        if ["queued", "running"].contains(job.status) { ProgressView(value: job.progress ?? 0) }
                        if let error = job.error { Text(error).font(.caption).foregroundStyle(.orange) }
                    }.panel()
                }
                if model.reviews.isEmpty { EmptyCard(symbol: "tray", title: "No hard frames yet", detail: "Low-confidence frames from approved runs appear here with their reason for review.").frame(height: 350) }
                else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 16)], spacing: 16) {
                        ForEach(model.reviews) { entry in
                            VStack(alignment: .leading, spacing: 12) {
                                ImageCanvas(path: model.resolveImagePath(entry.imagePath)).frame(height: 190)
                                Text(entry.reason).font(.callout)
                                HStack { StatusPill(text: entry.status, color: entry.status == "pending" ? .orange : Studio.muted); Spacer(); Button("Skip") { model.review(entry, status: "skipped") }; Button("Accept") { model.review(entry, status: "accepted") }.buttonStyle(.borderedProminent) }.disabled(model.busy || entry.status != "pending")
                            }.panel()
                        }
                    }
                }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }.sheet(isPresented: $trainingApproval) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Train a local detector").font(.title2.weight(.semibold))
                Text("Training starts from a pretrained detector or continues the selected local model. It needs at least 20 reviewed images. Your chosen 10–50 validation images are held out; only the reviewed remainder is used for training. Set a bounded epoch and time budget below.").font(.callout)
                Text("The saved model becomes a candidate only. It must be evaluated and explicitly approved before it can run as a deployment. Training quality is not guaranteed.").font(.callout).foregroundStyle(Studio.muted)
                Stepper("Epochs: \(trainingEpochs)", value: $trainingEpochs, in: 1...30)
                Stepper("Time limit: \(Int(trainingMinutes)) minutes", value: $trainingMinutes, in: 1...5, step: 1)
                HStack { Button("Cancel") { trainingApproval = false }; Spacer(); Button("Start local training") { trainingApproval = false; model.startTraining(epochs: trainingEpochs, maxMinutes: trainingMinutes) }.buttonStyle(.borderedProminent) }
            }.padding(30).frame(width: 500)
        }
    }
}
