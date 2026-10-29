import SwiftUI

struct LiveCaptureView: View {
    @EnvironmentObject var model: WorkspaceModel
    @ObservedObject var live: LiveCaptureModel
    let project: Project
    let candidateIndex: Int
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Live source").font(.headline)
                Spacer()
                StatusPill(text: live.state.replacingOccurrences(of: "_", with: " "), color: live.state == "failed" ? .orange : Studio.accent)
                if live.active {
                    Button("Stop capture", role: .destructive) { Task { await live.stop() } }.disabled(live.state == "stopping")
                } else {
                    Button(live.previewOnly ? "Start live preview" : "Start approved recording") { live.start(projectID: project.id, candidateIndex: candidateIndex) }
                        .buttonStyle(.borderedProminent)
                        .disabled(!live.ready || project.candidates.isEmpty || (!live.previewOnly && project.deploymentId == nil))
                }
            }
            HStack(spacing: 16) {
                Picker("Source", selection: $live.sourceKind) { ForEach(LiveSourceKind.allCases) { Text($0.label).tag($0) } }.frame(width: 260)
                switch live.sourceKind {
                case .recordedVideo:
                    Button("Choose video…") { live.chooseVideo() }; Text(live.sourceLabel).lineLimit(1).truncationMode(.middle).foregroundStyle(Studio.muted)
                case .camera:
                    if !live.cameras.isEmpty { Picker("Device", selection: $live.cameraID) { ForEach(live.cameras, id: \.uniqueID) { Text($0.localizedName).tag($0.uniqueID) } }.frame(maxWidth: 290) }
                    Button(live.cameras.isEmpty ? "Find cameras" : "Refresh cameras") { live.findCameras() }
                case .screenCapture:
                    Button(live.screenSelected ? "Change selection…" : "Choose display or window…") { live.chooseScreen() }
                    Text(live.screenSelected ? "Selected in macOS" : "macOS will ask what to share").foregroundStyle(Studio.muted)
                }
                Spacer()
            }.disabled(live.active).font(.callout)
            HStack(alignment: .top) {
                Picker("Output", selection: $live.previewOnly) {
                    Text("Preview only").tag(true)
                    Text("Record approved pipeline").tag(false)
                }.pickerStyle(.segmented).frame(width: 340).disabled(live.active)
                Text(live.previewOnly ? "Processes frames locally. Saves no evidence and sends no alerts." : "Saves accepted frames and rule events. Enabled alert destinations may receive rule messages.")
                    .font(.caption).foregroundStyle(Studio.muted).frame(maxWidth: .infinity, alignment: .leading)
            }
            if !live.previewOnly {
                Text("Requires an approved deployment. Recording stops at 240 retained frames or 256 MiB per session; existing evidence is kept.").font(.caption).foregroundStyle(Studio.muted)
            }
            if let error = live.error { Label(error, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange).textSelection(.enabled) }
            if let session = live.session {
                Text("Workflow sample rate: \(session.sampleFps, specifier: "%.1f") fps · Session limit: \(Int(session.maxDurationS / 60)) min\(session.warnings.isEmpty ? "" : " · " + session.warnings.joined(separator: " · "))")
                    .font(.caption).foregroundStyle(Studio.muted)
            }
            if let image = live.image {
                LiveResultCanvas(image: image, detections: live.frame?.detections ?? []).frame(minHeight: 300, idealHeight: 410)
                if let counts = live.frame?.counts, !counts.isEmpty { Text(counts.keys.sorted().map { "\($0): \(counts[$0] ?? 0)" }.joined(separator: " · ")).font(.callout.monospaced()) }
                if let texts = live.frame?.texts, !texts.isEmpty { Text(texts.joined(separator: " · ")).font(.callout).textSelection(.enabled) }
            } else {
                VStack(spacing: 10) {
                    Image(systemName: live.active ? "viewfinder" : "video").font(.system(size: 28)).foregroundStyle(Studio.muted)
                    Text(live.active ? "Waiting for the first processed frame" : "Select a source, then start preview or approved recording").font(.callout).foregroundStyle(Studio.muted)
                    if live.active { ProgressView().controlSize(.small) }
                }.frame(maxWidth: .infinity).frame(height: 160).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
            }
            if live.session != nil {
                HStack(spacing: 24) {
                    statistic("Processed", "\(live.processedFrames)")
                    statistic("Processing FPS", String(format: "%.2f", live.processingFps))
                    statistic("Latest inference", String(format: "%.0f ms", live.processingMs))
                    statistic("Dropped (busy)", "\(live.droppedFrames)")
                    statistic("Sampled out", "\(live.sampledFrames)")
                    statistic("Retained", "\(live.retainedFrames) · \(ByteCountFormatter.string(fromByteCount: Int64(live.retainedBytes), countStyle: .file))")
                    Spacer()
                }
                Text("The overlay belongs to the displayed processed frame. Frames arriving during inference are dropped; no backlog is queued.").font(.caption).foregroundStyle(Studio.muted)
            }
        }.panel()
            .onChange(of: live.state) { _, state in
                if ["stopped", "limit_reached", "failed"].contains(state), live.session?.previewOnly == false {
                    Task { try? await model.loadEvidence() }
                }
            }
            .onChange(of: live.sourceKind) { _, _ in live.closePicker() }
            .onDisappear { Task { await live.stop() } }
    }
    private func statistic(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(value).font(.system(.callout, design: .monospaced).weight(.semibold)); Text(title).font(.caption2).foregroundStyle(Studio.muted) }
    }
}
struct LiveResultCanvas: View {
    let image: NSImage
    let detections: [Detection]
    var body: some View {
        GeometryReader { geometry in
            let rect = ImageGeometry.fittedRect(image: image.size, container: geometry.size)
            ZStack(alignment: .topLeading) {
                Color.black
                Image(nsImage: image).resizable().frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY)
                ForEach(Array(detections.enumerated()), id: \.offset) { _, detection in
                    if detection.box.count == 4 {
                        let box = AnnotationGeometry.boxRect(detection.box, image: rect)
                        Rectangle().stroke(Studio.accent, lineWidth: 2).frame(width: max(0, box.width), height: max(0, box.height)).position(x: box.midX, y: box.midY)
                        Text("\(detection.label) \(Int(detection.confidence * 100))%")
                            .font(.system(size: 10, weight: .semibold)).padding(3).background(Studio.accent).foregroundStyle(.black)
                            .offset(x: max(rect.minX, box.minX), y: max(rect.minY, box.minY - 20))
                    }
                }
            }.clipped().clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }
}
