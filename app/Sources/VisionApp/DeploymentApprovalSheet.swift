import SwiftUI

struct DeploymentApprovalSheet: View {
    @EnvironmentObject var model: WorkspaceModel
    let dismiss: () -> Void
    @NativeState<String> private var overrideReason = ""
    @NativeState<EvidenceApprovalScope> private var scope = .promotion
    private var canApprove: Bool {
        !model.busy && model.supervisor.connected && model.selectedID.map { !model.agentWorkspace(for: $0).running } == true && EvidenceApprovalPresentation.canApprove(model.evaluation, scope: scope, reason: overrideReason)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Approve your application").font(.title2.weight(.semibold))
            Text(model.candidate?.name ?? "Selected application").font(.headline).foregroundStyle(Studio.accent)
            if let result = model.evaluation {
                Text("Evaluated against \(result.sampleCount) reviewed images. The engine verifies that the application and labels still match this evidence.").font(.callout)
                Text("\(EvaluationPresentation.metricName(result.metric)): \(EvaluationPresentation.format(EvaluationPresentation.measuredValue(result), metric: result.metric)) · Target \(EvaluationPresentation.target(result)) · \(result.passed ? "met" : "missed")").font(.caption.monospaced()).foregroundStyle(result.passed ? Studio.accent : .orange)
                EvaluationQualityView(result: result)
                Picker("Approval scope", selection: $scope) { ForEach(EvidenceApprovalScope.allCases, id: \.self) { Text($0.title).tag($0) } }.pickerStyle(.segmented)
                if scope == .localTrial {
                    Text("Local trial; external alert delivery disabled.").font(.callout.weight(.semibold)).foregroundStyle(.orange)
                    Text("Allows bounded local recording without claiming validated quality. Temporal event quality remains unmeasured. The engine enforces run and live limits; approved limits remain visible with this application.").font(.caption).foregroundStyle(Studio.muted)
                    TextField("Why proceed with a local trial? (at least 10 characters)", text: $overrideReason, axis: .vertical).lineLimit(2...4).textFieldStyle(.roundedBorder)
                } else {
                    Text("Requires a passing independent acceptance test and eligible current evidence for the stated scope. Approval allows local recording and rule alerts to destinations you enabled; it does not establish temporal event accuracy.").font(.caption).foregroundStyle(Studio.muted)
                }
            } else { Text("Current evaluation evidence is required before approval.").font(.callout).foregroundStyle(.orange) }
            if model.project?.synthetic == true { Text("This evaluation uses synthetic imagery. It does not establish accuracy on real-world footage.").font(.caption).foregroundStyle(.orange) }
            HStack {
                Button("Cancel", action: dismiss); Spacer()
                Button(scope == .localTrial ? "Approve local trial" : "Approve quality promotion") { dismiss(); model.approveDeployment(override: scope == .localTrial ? overrideReason : nil, scope: scope) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!canApprove)
            }
        }.padding(30).frame(width: 580)
    }
}
