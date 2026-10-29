import SwiftUI

enum TextComparisonMode: String, Codable {
    case exact, contains
    var label: String { self == .exact ? "Exact value match" : "Contains expected text" }
}

struct TextComparison: Codable {
    let blockID: String
    let expected: String
    let observed: [String]
    let mode: TextComparisonMode
    let matched: Bool
    var resultLabel: String { matched ? "Pass" : "Fail" }
    enum CodingKeys: String, CodingKey { case blockID = "block_id", expected, observed, mode, matched }
}

enum TextComparisonPresentation {
    static func expectsComparison(_ pipeline: Pipeline?) -> Bool {
        pipeline?.blocks.contains { $0.type == "match" } == true
    }
    static func isVisible(frame: FrameResult, pipeline: Pipeline?) -> Bool {
        !(frame.comparisons ?? []).isEmpty || expectsComparison(pipeline)
    }
}

struct TextComparisonEvidence: View {
    let comparisons: [TextComparison]
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Text comparisons").font(.caption.weight(.semibold))
            if comparisons.isEmpty {
                Text("No comparison result was recorded for this sample. Run a fresh preview to inspect it.")
                    .font(.caption).foregroundStyle(Studio.muted)
            } else {
                ForEach(Array(comparisons.enumerated()), id: \.offset) { _, comparison in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Label(comparison.resultLabel, systemImage: comparison.matched ? "checkmark.circle" : "xmark.circle")
                                .font(.caption.weight(.semibold)).foregroundStyle(comparison.matched ? Studio.accent : .orange)
                            Text("\(comparison.blockID) · \(comparison.mode.label)").font(.caption).foregroundStyle(Studio.muted)
                            Spacer(minLength: 0)
                        }
                        rawValue("Expected", value: comparison.expected)
                        Text("Observed").font(.caption2.weight(.medium)).foregroundStyle(Studio.muted)
                        if comparison.observed.isEmpty {
                            Text("No text values were recognized.").font(.caption).foregroundStyle(Studio.muted)
                        } else {
                            ScrollView {
                                LazyVStack(alignment: .leading, spacing: 7) {
                                    ForEach(Array(comparison.observed.enumerated()), id: \.offset) { _, value in
                                        rawValue(nil, value: value)
                                    }
                                }.frame(maxWidth: .infinity, alignment: .leading)
                            }.frame(maxHeight: 170)
                        }
                    }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Studio.raised).clipShape(RoundedRectangle(cornerRadius: 7))
                }
                Text("Pass/fail reflects this comparison of recognized text. It does not measure OCR accuracy.")
                    .font(.caption2).foregroundStyle(Studio.muted)
            }
        }
    }
    private func rawValue(_ label: String?, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if let label { Text(label).font(.caption2.weight(.medium)).foregroundStyle(Studio.muted) }
            Text(value.isEmpty ? "(empty value)" : value).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
            DisclosureGroup("Unicode code points") {
                Text(ReadingPresentation.codePoints(value)).font(.caption2.monospaced()).textSelection(.enabled)
            }.font(.caption2).foregroundStyle(Studio.muted)
        }
    }
}
