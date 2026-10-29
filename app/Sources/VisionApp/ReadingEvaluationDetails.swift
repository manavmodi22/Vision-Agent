import SwiftUI

struct ReadingEvaluationDetails: View {
    let evaluation: Evaluation
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Text accuracy measures per-image equality of normalized text lists.").font(.caption).foregroundStyle(Studio.muted)
            if evaluation.characterErrorRate != nil || evaluation.wordErrorRate != nil {
                HStack(spacing: 25) {
                    if let value = evaluation.characterErrorRate { rate("Character error rate", value) }
                    if let value = evaluation.wordErrorRate { rate("Word error rate", value) }
                }
                Text("Edit errors divided by expected characters or words. Insertions can make a rate exceed 100%.").font(.caption2).foregroundStyle(Studio.muted)
            }
            if let normalization = evaluation.textNormalization { Text("Normalization: " + normalization).font(.caption2).foregroundStyle(Studio.muted).textSelection(.enabled) }
            if let counts = evaluation.textErrorCounts, !counts.isEmpty { StructuredDetail(title: "Recorded text edit counts", value: counts) }
        }
    }
    private func rate(_ title: String, _ value: Double) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(title).font(.caption2).foregroundStyle(Studio.muted); Text(String(format: "%.1f%%", value * 100)).font(.callout.monospaced()) }
    }
}
