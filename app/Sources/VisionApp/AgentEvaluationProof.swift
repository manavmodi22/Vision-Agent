import SwiftUI

struct AgentEvaluationProof: View {
    @EnvironmentObject var model: WorkspaceModel
    let build: AgentBuildStatus
    let busy: Bool
    let approve: () -> Void
    let train: () -> Void
    var correctImage: ((String) -> Void)?
    var reviewAnnotations: (() -> Void)?
    var editEvidence: (() -> Void)?
    @NativeState<Int?> private var inspectedIndex: Int?
    private var index: Int { let desired = inspectedIndex ?? build.selectedCandidateIndex ?? 0; return build.evaluations.indices.contains(desired) ? desired : 0 }
    private var result: Evaluation? { build.evaluations.indices.contains(index) ? build.evaluations[index] : nil }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack { Text(build.running ? "Previous measured results · updating" : "Measured results").font(.headline); Spacer(); Text("\(build.evaluations.count) candidate\(build.evaluations.count == 1 ? "" : "s")").font(.caption).foregroundStyle(Studio.muted) }
            Text("These scores use the reviewed evaluation images and the workflow’s selected classes and regions. Inspect a candidate below to see its misses.").font(.caption).foregroundStyle(Studio.muted)
            ForEach(Array(build.evaluations.enumerated()), id: \.offset) { candidateIndex, evaluation in
                Button { inspectedIndex = candidateIndex } label: { comparisonRow(candidateIndex, evaluation) }.buttonStyle(.plain)
                    .accessibilityLabel("Inspect evaluation for candidate \(candidateIndex + 1)")
            }
            if let result {
                EvaluationQualityView(result: result, edit: editEvidence).disabled(busy)
                if result.metric == "text_accuracy" { ReadingEvaluationDetails(evaluation: result) }
                ForEach(result.warnings ?? [], id: \.self) { warning in Label(warning, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                Divider()
                HStack { Text("Failures · candidate \(index + 1)").font(.callout.weight(.semibold)); Spacer(); Text("\(result.failures.count) images").font(.caption).foregroundStyle(Studio.muted) }
                if result.failures.isEmpty {
                    Text("No failing images were reported for this evaluation. This is not evidence of performance beyond the reviewed set.").font(.caption).foregroundStyle(Studio.muted)
                } else {
                    Text("Worst reported errors first. Correct the labels only where ground truth is wrong; model misses remain evaluation evidence.").font(.caption).foregroundStyle(Studio.muted)
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], alignment: .leading, spacing: 12) {
                        ForEach(Array(result.failures.prefix(8).enumerated()), id: \.offset) { failureIndex, value in failureCard(EvaluatedFailure(value, index: failureIndex), metric: result.metric) }
                    }
                    if result.failures.count > 8 { Text("Showing the 8 worst reported failures.").font(.caption2).foregroundStyle(Studio.muted) }
                }
            }
            if let acceptance = build.acceptanceEvaluation {
                Divider()
                Text("Acceptance · selected candidate").font(.headline)
                Text("\(EvaluationPresentation.metricName(acceptance.metric)): \(EvaluationPresentation.format(EvaluationPresentation.measuredValue(acceptance), metric: acceptance.metric)) · Target \(EvaluationPresentation.target(acceptance)) · \(acceptance.passed ? "met" : "missed") · \(acceptance.sampleCount) reviewed images").font(.caption.monospaced())
                EvaluationQualityView(result: acceptance, edit: editEvidence).disabled(busy)
                ForEach(acceptance.warnings ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
                if !acceptance.failures.isEmpty {
                    Text("Acceptance failures").font(.callout.weight(.semibold))
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], alignment: .leading, spacing: 12) {
                        ForEach(Array(acceptance.failures.prefix(4).enumerated()), id: \.offset) { failureIndex, value in failureCard(EvaluatedFailure(value, index: failureIndex), metric: acceptance.metric) }
                    }
                }
            }
            if build.status == "awaiting_improvement", let selected = build.selectedCandidateIndex, build.evaluations.indices.contains(selected) {
                Divider()
                Text(build.evaluations[selected].passed ? "The selected candidate needs stronger evidence." : "The selected candidate missed its target.").font(.callout.weight(.semibold)).foregroundStyle(.orange)
                Text("Improve examples and re-evaluate, allow a bounded training attempt when eligible, or explicitly review an override. None of these results grants approval automatically.").font(.caption).foregroundStyle(Studio.muted)
                HStack {
                    Button("Review annotations") { if let reviewAnnotations { reviewAnnotations() } else { model.section = "Dataset" } }
                    if build.nextAction == "approve_training" { Button("Review training request", action: train) }
                    Spacer()
                    Button("Review bounded local trial", action: approve)
                }.disabled(busy)
            }
        }.panel().onChange(of: build.id) { _, _ in inspectedIndex = nil }
    }
    private func comparisonRow(_ candidateIndex: Int, _ evaluation: Evaluation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(build.project.candidates.indices.contains(candidateIndex) ? build.project.candidates[candidateIndex].name : "Candidate \(candidateIndex + 1)").font(.callout.weight(.medium)).lineLimit(2)
                Spacer()
                if candidateIndex == build.selectedCandidateIndex { Text("Agent selection").font(.caption2).foregroundStyle(Studio.accent) }
                Text(evaluation.passed ? "Target met" : "Target missed").font(.caption).foregroundStyle(evaluation.passed ? Studio.accent : .orange)
            }
            Text(EvaluationEvidencePresentation.scope(evaluation)).font(.caption2).foregroundStyle(Studio.muted)
            HStack(alignment: .top, spacing: 20) {
                fact("Metric", EvaluationPresentation.metricName(evaluation.metric))
                fact("Measured", EvaluationPresentation.format(EvaluationPresentation.measuredValue(evaluation), metric: evaluation.metric))
                fact("Target", EvaluationPresentation.target(evaluation))
                fact("Reviewed images", "\(evaluation.sampleCount)")
            }
        }.padding(13).frame(maxWidth: .infinity, alignment: .leading).background(index == candidateIndex ? Studio.raised : Studio.background)
            .clipShape(RoundedRectangle(cornerRadius: 8)).overlay(RoundedRectangle(cornerRadius: 8).stroke(index == candidateIndex ? Studio.accent.opacity(0.5) : .clear))
    }
    private func fact(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) { Text(title).font(.caption2).foregroundStyle(Studio.muted); Text(value).font(.system(size: 12, weight: .medium, design: .monospaced)) }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func failureCard(_ failure: EvaluatedFailure, metric: String) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            ImageCanvas(path: failure.imagePath, emptyTitle: "Image unavailable", emptyDetail: "The evaluation did not provide a readable image.").frame(height: 145)
            Text(failure.imagePath.map { URL(fileURLWithPath: $0).lastPathComponent } ?? "Unidentified image").font(.caption.weight(.medium)).lineLimit(1)
            if metric == "text_accuracy" {
                Text("Expected: \(textValues(failure.texts("expected_texts")))").font(.caption).textSelection(.enabled)
                Text("Observed: \(textValues(failure.texts("observed_texts")))").font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled)
            } else {
                HStack { count("Expected", failure.number("expected_count")); count("Observed", failure.number("observed_count")) }
                Text("Missed: \(integer(failure.number("false_negatives"))) · Extra: \(integer(failure.number("false_positives")))").font(.caption).foregroundStyle(Studio.muted)
                if let error = failure.number("count_error") { Text(String(format: "Count error: %.3f", error)).font(.caption2).foregroundStyle(Studio.muted) }
            }
            if let error = failure.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            Button("Correct this image") { if let path = failure.imagePath { if let correctImage { correctImage(path) } else { model.openEvaluatedImage(path) } } }.disabled(busy || failure.imagePath == nil)
        }.padding(11).frame(maxWidth: .infinity, alignment: .leading).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
    }
    private func textValues(_ values: [String]?) -> String { guard let values else { return "Not reported" }; return values.isEmpty ? "(none)" : values.joined(separator: " · ") }
    private func integer(_ value: Double?) -> String { value.map { String(format: "%.0f", $0) } ?? "—" }
    private func count(_ label: String, _ value: Double?) -> some View { Text("\(label): \(integer(value))").font(.caption).frame(maxWidth: .infinity, alignment: .leading) }
}
