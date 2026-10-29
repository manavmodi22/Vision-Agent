import SwiftUI

struct ReadingOverlay: View {
    let readings: [DisplayReading]
    let rect: CGRect
    let selectedID: String?
    var onSelect: ((String) -> Void)? = nil
    var body: some View {
        ForEach(readings) { item in
            if let polygon = item.observation.polygon, let box = item.observation.box {
                let selected = selectedID == item.id
                Path { path in
                    for (index, point) in polygon.enumerated() {
                        let p = CGPoint(x: rect.minX+point[0]*rect.width, y: rect.minY+point[1]*rect.height)
                        if index == 0 { path.move(to: p) } else { path.addLine(to: p) }
                    }
                    path.closeSubpath()
                }.stroke(selected ? Color.yellow : .cyan, style: StrokeStyle(lineWidth: selected ? 3 : 1.5, dash: [5, 3]))
                    .allowsHitTesting(false)
                Button { onSelect?(item.id) } label: {
                    Text("\(item.index+1)").font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .padding(.horizontal, 5).padding(.vertical, 2).background(selected ? Color.yellow : .cyan).foregroundStyle(.black)
                }.buttonStyle(.plain).offset(x: rect.minX+box[0]*rect.width, y: max(rect.minY, rect.minY+box[1]*rect.height-18))
            }
        }
    }
}

struct ReadingEvidenceView: View {
    let blocks: [FrameInference]
    @Binding var selectedID: String?
    var compact = false
    private var rows: [DisplayReading] { ReadingPresentation.readings(blocks) }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Reader observations").font(.caption.weight(.semibold))
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(blocks, id: \.blockID) { block in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text("\(block.result.task == "barcode" ? "Barcode" : "OCR") · \(block.result.identity.modelID)").font(.caption.weight(.medium))
                                Spacer()
                                Text(String(format: "%.0f ms", block.result.timing.totalMs)).font(.caption.monospaced()).foregroundStyle(Studio.muted)
                            }
                            if block.result.readings.isEmpty { Text("No values recognized by this reader.").font(.caption).foregroundStyle(Studio.muted) }
                            ForEach(rows.filter { $0.blockID == block.blockID }) { row in
                                Button { selectedID = row.id } label: {
                                    HStack(alignment: .top, spacing: 7) {
                                        Text("\(row.index+1)").font(.caption.monospaced()).foregroundStyle(.cyan).frame(width: 22)
                                        VStack(alignment: .leading, spacing: 3) {
                                            Text(row.observation.text.isEmpty ? "(empty value)" : row.observation.text).font(.system(size: 12, design: .monospaced)).lineLimit(3)
                                            Text(metadata(row.observation)).font(.caption2).foregroundStyle(Studio.muted)
                                        }
                                        Spacer(minLength: 0)
                                    }.padding(6).frame(maxWidth: .infinity, alignment: .leading)
                                        .background(selectedID == row.id ? Color.cyan.opacity(0.12) : .clear).clipShape(RoundedRectangle(cornerRadius: 5))
                                }.buttonStyle(.plain)
                            }
                            ForEach(block.result.warnings, id: \.self) { Text($0).font(.caption2).foregroundStyle(.orange).textSelection(.enabled) }
                            DisclosureGroup("Reader identity · \(block.blockID)") {
                                Text("Adapter: \(block.result.identity.adapterID)\nProvider: \(block.result.identity.provider)\nScope: \(block.result.identity.identityScope)\nIdentity: \(block.result.identity.identityHash)")
                                    .font(.caption2.monospaced()).textSelection(.enabled)
                                ForEach(block.result.identity.systemIdentity.keys.sorted(), id: \.self) { key in
                                    Text("\(key): \(block.result.identity.systemIdentity[key] ?? "")").font(.caption2.monospaced()).textSelection(.enabled)
                                }
                            }.font(.caption2).foregroundStyle(Studio.muted)
                        }
                    }
                }
            }.frame(maxHeight: compact ? 150 : 220)
            if let selected = rows.first(where: { $0.id == selectedID }) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Raw recognized value").font(.caption.weight(.medium))
                    Text(selected.observation.text).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
                    DisclosureGroup("Unicode code points") {
                        Text(ReadingPresentation.codePoints(selected.observation.text)).font(.caption2.monospaced()).textSelection(.enabled)
                    }.font(.caption2).foregroundStyle(Studio.muted)
                }
            }
            if !compact { Text("Reader confidence is a native score, not measured accuracy. Correct expected values through image review; predictions do not become labels automatically.").font(.caption2).foregroundStyle(Studio.muted) }
        }
    }
    private func metadata(_ value: ReadingObservation) -> String {
        var fields = [value.box == nil ? "Geometry not provided" : "Observed region"]
        if let symbology = value.symbology { fields.append(symbology) }
        if let confidence = value.confidence { fields.append(String(format: "Native confidence %.3f", confidence)) }
        else { fields.append("Confidence not provided") }
        return fields.joined(separator: " · ")
    }
}
