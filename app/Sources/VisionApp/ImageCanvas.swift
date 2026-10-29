import SwiftUI

struct ImageGeometry {
    static func fittedRect(image: CGSize, container: CGSize) -> CGRect {
        guard image.width > 0, image.height > 0 else { return .zero }
        let ratio = min(container.width / image.width, container.height / image.height)
        let size = CGSize(width: image.width * ratio, height: image.height * ratio)
        return CGRect(x: (container.width-size.width)/2, y: (container.height-size.height)/2, width: size.width, height: size.height)
    }
    static func normalizedBox(start: CGPoint, end: CGPoint, rect: CGRect) -> [Double]? {
        guard rect.width > 0, rect.height > 0, rect.contains(start) else { return nil }
        let x1 = max(0, min(1, (min(start.x, end.x)-rect.minX)/rect.width))
        let y1 = max(0, min(1, (min(start.y, end.y)-rect.minY)/rect.height))
        let x2 = max(0, min(1, (max(start.x, end.x)-rect.minX)/rect.width))
        let y2 = max(0, min(1, (max(start.y, end.y)-rect.minY)/rect.height))
        guard x2-x1 > 0.005, y2-y1 > 0.005 else { return nil }
        return [x1, y1, x2, y2]
    }
}

struct ImageCanvas: View {
    let path: String?
    var detections: [Detection] = []
    var zones: [Zone] = []
    var readings: [DisplayReading] = []
    var selectedReadingID: String? = nil
    var onReadingSelect: ((String) -> Void)? = nil
    var onDraw: (([Double]) -> Void)?
    var emptyTitle = "Your sample preview"
    var emptyDetail = "Import media and run a candidate to inspect detections and counts."
    @NativeState<CGPoint?> private var dragStart: CGPoint?
    @NativeState<CGPoint?> private var dragEnd: CGPoint?
    var body: some View {
        GeometryReader { geometry in
            if let path, let image = NSImage(contentsOfFile: path) {
                let rect = ImageGeometry.fittedRect(image: image.size, container: geometry.size)
                ZStack(alignment: .topLeading) {
                    Color.black.opacity(0.35)
                    Image(nsImage: image).resizable().interpolation(.high).frame(width: rect.width, height: rect.height).position(x: rect.midX, y: rect.midY)
                    ForEach(zones) { zone in
                        Path { p in
                            for (index, point) in zone.polygon.enumerated() where point.count == 2 {
                                let v = CGPoint(x: rect.minX + point[0]*rect.width, y: rect.minY+point[1]*rect.height)
                                if index == 0 { p.move(to: v) } else { p.addLine(to: v) }
                            }
                            p.closeSubpath()
                        }.fill(Studio.accent.opacity(0.12))
                        Path { p in
                            for (index, point) in zone.polygon.enumerated() where point.count == 2 {
                                let v = CGPoint(x: rect.minX + point[0]*rect.width, y: rect.minY+point[1]*rect.height)
                                if index == 0 { p.move(to: v) } else { p.addLine(to: v) }
                            }; p.closeSubpath()
                        }.stroke(Studio.accent, style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                        if let first = zone.polygon.first, first.count == 2 {
                            Text(zone.id).font(.caption.bold()).padding(4).background(Studio.accent).foregroundStyle(.black)
                                .offset(x: rect.minX+first[0]*rect.width+4, y: rect.minY+first[1]*rect.height+4)
                        }
                    }
                    ForEach(Array(detections.enumerated()), id: \.offset) { _, detection in
                        if detection.box.count == 4 {
                            let box = detection.box
                            let x = rect.minX+box[0]*rect.width, y = rect.minY+box[1]*rect.height
                            Rectangle().stroke(Studio.accent, lineWidth: 2).frame(width: (box[2]-box[0])*rect.width, height: (box[3]-box[1])*rect.height).offset(x: x, y: y)
                            Text("\(detection.label)  \(Int(detection.confidence*100))%")
                                .font(.system(size: 10, weight: .semibold, design: .monospaced)).padding(.horizontal, 5).padding(.vertical, 3)
                                .foregroundStyle(.black).background(Studio.accent).offset(x: x, y: max(rect.minY, y-20))
                        }
                    }
                    ReadingOverlay(readings: readings, rect: rect, selectedID: selectedReadingID, onSelect: onReadingSelect)
                    if let start = dragStart, let end = dragEnd {
                        Rectangle().fill(Studio.accent.opacity(0.2)).overlay(Rectangle().stroke(Studio.accent, lineWidth: 2))
                            .frame(width: abs(end.x-start.x), height: abs(end.y-start.y))
                            .offset(x: min(start.x,end.x), y: min(start.y,end.y))
                    }
                }.contentShape(Rectangle()).gesture(
                    DragGesture(minimumDistance: 3).onChanged { value in
                        guard onDraw != nil else { return }; dragStart = value.startLocation; dragEnd = value.location
                    }.onEnded { value in
                        defer { dragStart = nil; dragEnd = nil }
                        if let box = ImageGeometry.normalizedBox(start: value.startLocation, end: value.location, rect: rect) { onDraw?(box) }
                    }
                )
            } else {
                EmptyCard(symbol: "photo.on.rectangle.angled", title: emptyTitle, detail: emptyDetail)
            }
        }.clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

enum PreviewPresentation {
    static func agentCanvasHeight(width: CGFloat) -> CGFloat { min(700, max(320, (width - 40) * 9 / 16)) }
    static func detectionCounts(_ detections: [Detection]) -> [String: Int] {
        Dictionary(grouping: detections, by: \.label).mapValues(\.count)
    }
    static func zones(for pipeline: Pipeline?, savedZones: [Zone]) -> [Zone] {
        guard let filter = pipeline?.blocks.first(where: { $0.type == "zone_filter" }) else { return [] }
        switch filter.params?["zones"] {
        case nil: return savedZones // The registered block defaults to zones/lanes.json.
        case .string(let path): return path == "zones/lanes.json" ? savedZones : []
        case .array(let values):
            guard let data = try? JSONEncoder().encode(values), let zones = try? JSONDecoder().decode([Zone].self, from: data) else { return [] }
            return zones
        default: return []
        }
    }
}

struct PreviewPanel: View {
    @EnvironmentObject var model: WorkspaceModel
    var agentContext = false
    var agentBuilding = false
    @NativeState<CGFloat> private var availableWidth = 0
    @NativeState<String?> private var selectedReadingID: String?
    private var waitingMessage: String {
        if model.previewRequestID != nil { return "Running this candidate on your examples…" }
        if agentContext { return agentBuilding ? "The agent is building and testing your app. Preview results will appear here." : "No model output yet. Build progress and next steps appear in the conversation." }
        return "Input sample — run preview to see model output."
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack { Eyebrow(text: agentContext && model.previewIsPrevious && model.frame != nil ? "Previous preview · updating app" : model.frame == nil ? "Input sample" : "Model output"); Spacer(); if let f = model.frame { Text(String(format: "%.0f ms / frame", f.elapsedMs)).font(.caption.monospaced()).foregroundStyle(Studio.muted) } }
            ImageCanvas(path: model.frame?.imagePath ?? model.project?.media.first, detections: model.frame?.detections ?? [], zones: model.previewIsPrevious ? [] : PreviewPresentation.zones(for: model.displayedPreviewPipeline, savedZones: model.zonesConfirmed ? model.zones : []), readings: ReadingPresentation.readings(ReadingPresentation.blocks(model.frame)), selectedReadingID: selectedReadingID, onReadingSelect: { selectedReadingID = $0 }, emptyTitle: agentContext ? "Application preview" : "Your sample preview", emptyDetail: waitingMessage)
                .frame(minHeight: agentContext ? PreviewPresentation.agentCanvasHeight(width: availableWidth) : 260,
                       maxHeight: agentContext ? PreviewPresentation.agentCanvasHeight(width: availableWidth) : nil)
            if let frames = model.preview?.frames, !frames.isEmpty {
                HStack {
                    Button { model.frameIndex = max(0, model.frameIndex-1) } label: { Image(systemName: "chevron.left") }.disabled(model.frameIndex == 0)
                    Text("Sample \(model.frameIndex+1) of \(frames.count)").font(.caption.monospaced())
                    Button { model.frameIndex = min(frames.count-1, model.frameIndex+1) } label: { Image(systemName: "chevron.right") }.disabled(model.frameIndex == frames.count-1)
                    Spacer()

                }
                if let frame = model.frame {
                    let classes = PreviewPresentation.detectionCounts(frame.detections)
                    if classes.isEmpty && EvaluationPresentation.hasDetector(model.displayedPreviewPipeline) { Text("No object detections in this frame.").font(.caption).foregroundStyle(Studio.muted) }
                    if !classes.isEmpty {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), alignment: .leading)], alignment: .leading, spacing: 7) {
                            ForEach(classes.keys.sorted(), id: \.self) { label in StatusPill(text: "\(label): \(classes[label] ?? 0)") }
                        }
                    }
                    let zones = frame.counts.filter { $0.key != "all" }
                    if !zones.isEmpty { Text("Zone totals · " + zones.keys.sorted().map { "\($0): \(zones[$0] ?? 0)" }.joined(separator: " · ")).font(.caption).foregroundStyle(Studio.muted) }
                    let readers = ReadingPresentation.blocks(frame)
                    if !readers.isEmpty { ReadingEvidenceView(blocks: readers, selectedID: $selectedReadingID) }
                    if let output = ReadingPresentation.workflowText(frame, pipeline: model.displayedPreviewPipeline) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Workflow text output").font(.caption.weight(.medium))
                            Text(output.values.isEmpty ? "No text output in this sample." : output.values.joined(separator: " · ")).font(.callout).textSelection(.enabled)
                            if output.readerEvidenceUnavailable { Text("Reader region evidence is unavailable for this result.").font(.caption2).foregroundStyle(Studio.muted) }
                        }
                    }
                    if PreviewOutcomePresentation.hasEventSink(model.displayedPreviewPipeline) || !frame.events.isEmpty {
                        PreviewRuleOutcome(events: frame.events, recorded: model.previewIsRecorded)
                    }
                }
            } else { Text(waitingMessage).font(.caption).foregroundStyle(Studio.muted) }
        }.panel()
            .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { availableWidth = $0 }
            .onChange(of: model.frame?.imagePath) { _, _ in selectedReadingID = nil }
    }
}
