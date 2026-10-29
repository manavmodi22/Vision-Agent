import SwiftUI

struct DeploymentApprovalSheet: View {
    @EnvironmentObject var model: WorkspaceModel
    let dismiss: () -> Void
    @NativeState<String> private var overrideReason = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Approve your application").font(.title2.weight(.semibold))
            Text(model.candidate?.name ?? "Selected application").font(.headline).foregroundStyle(Studio.accent)
            if let result = model.evaluation {
                Text("Evaluated against \(result.sampleCount) reviewed images. The engine verifies that the application and labels still match this evidence.").font(.callout)
                Text("\(EvaluationPresentation.metricName(result.metric)): \(EvaluationPresentation.format(EvaluationPresentation.measuredValue(result), metric: result.metric)) · Target \(EvaluationPresentation.target(result)) · \(result.passed ? "met" : "missed")").font(.caption.monospaced()).foregroundStyle(result.passed ? Studio.accent : .orange)
                Text("Approval allows local runs to save evidence and send rule alerts to destinations you enabled.").font(.callout).foregroundStyle(Studio.muted)
                if !result.passed {
                    Text("The target was missed. Explain why you want to proceed with this result.").foregroundStyle(.orange).font(.callout)
                    TextField("Override reason (at least 10 characters)", text: $overrideReason).textFieldStyle(.roundedBorder)
                }
            } else { Text("Current evaluation evidence is required before approval.").font(.callout).foregroundStyle(.orange) }
            if model.project?.synthetic == true { Text("This evaluation uses synthetic imagery. It does not establish accuracy on real-world footage.").font(.caption).foregroundStyle(.orange) }
            HStack {
                Button("Cancel", action: dismiss); Spacer()
                Button("Approve application") { dismiss(); model.approveDeployment(override: model.evaluation?.passed == true ? nil : overrideReason) }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.evaluation == nil || (model.evaluation?.passed != true && overrideReason.trimmingCharacters(in: .whitespaces).count < 10))
            }
        }.padding(30).frame(width: 510)
    }
}
