import SwiftUI

struct EvaluationQualityView: View {
    let result: Evaluation
    var edit: (() -> Void)?
    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(EvaluationEvidencePresentation.scope(result)).font(.caption.weight(.medium)).foregroundStyle(Studio.muted)
                    Text(EvaluationEvidencePresentation.qualityTitle(result)).font(.callout.weight(.semibold))
                        .foregroundStyle(EvaluationEvidencePresentation.canPromote(result) ? Studio.accent : .orange)
                }
                Spacer()
                if let edit { Button("Edit evaluation evidence", action: edit).font(.caption) }
            }
            ForEach(EvaluationEvidencePresentation.reasons(result), id: \.self) { Text($0).font(.caption).textSelection(.enabled) }
            Text("The numeric target describes these images. Promotion evidence depends on the declared scope, independent groups and their prior use.")
                .font(.caption2).foregroundStyle(Studio.muted)
            if let id = result.protocolID, let hash = result.protocolHash {
                DisclosureGroup("Protocol identity") { Text("\(id)\n\(hash)").font(.caption2.monospaced()).textSelection(.enabled) }.font(.caption2).foregroundStyle(Studio.muted)
            }
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
