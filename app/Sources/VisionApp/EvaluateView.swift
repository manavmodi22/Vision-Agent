import SwiftUI

struct EvaluateView: View {
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<Int> private var annotationIndex = 0
    @NativeState<String> private var label = "pallet"
    @NativeState<Bool> private var showApproval = false
    @NativeState<Bool> private var labelsEdited = false
    private var current: Annotation? {
        guard let annotations = model.dataset?.annotations, annotations.indices.contains(annotationIndex) else { return nil }
        return annotations[annotationIndex]
    }
    private var result: Evaluation? { model.evaluation }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack { Text("Evaluation evidence for your application").font(.callout).foregroundStyle(Studio.muted); Spacer(); Button("Continue building") { model.returnToAgent() }.buttonStyle(.borderedProminent).disabled(model.busy || labelsEdited) }
                HStack {
                    VStack(alignment: .leading, spacing: 6) { Eyebrow(text: "03 / Prove"); Text("Check labels. Measure the misses.").font(.title3.weight(.medium)) }
                    Spacer()
                    Button("Suggest labels with detector") { model.suggestLabels() }.disabled(model.busy || !EvaluationPresentation.hasDetector(model.candidate)).help("The selected detector proposes unreviewed boxes. Existing reviewed labels are preserved.")
                    Button("Save labels") { model.saveAnnotations { labelsEdited = false } }.disabled(model.busy || model.dataset == nil)
                    Button { model.evaluate() } label: { Label("Evaluate candidate", systemImage: "checkmark.shield") }.buttonStyle(.borderedProminent).disabled(model.busy || model.candidate == nil)
                }
                if labelsEdited { Text("Save your label edits before continuing or approving this application.").font(.caption).foregroundStyle(.orange) }
                Text("Detector suggestions remain unreviewed until you confirm or correct each image. Reviewed labels are preserved.").font(.caption).foregroundStyle(Studio.muted)
                if let result {
                    HStack(spacing: 14) {
                        if result.metric == "text_accuracy" {
                            MetricCard(title: "Text accuracy", value: EvaluationPresentation.format(result.textAccuracy, metric: result.metric), caption: "Images with matching normalized text lists")
                        } else {
                            MetricCard(title: "Precision", value: String(format: "%.1f%%", result.precision*100), caption: "Correct detections / detections")
                            MetricCard(title: "Recall", value: String(format: "%.1f%%", result.recall*100), caption: "Found objects / labelled objects")
                            MetricCard(title: "Count MAE", value: String(format: "%.3f", result.countMae), caption: "Mean absolute count error")
                        }
                        MetricCard(title: "Eval images", value: "\(result.sampleCount)", caption: "Reviewed images in this set")
                    }
                    HStack(spacing: 14) {
                        StatusPill(text: result.passed ? "Target met" : "Target missed", color: result.passed ? Studio.accent : .orange)
                        Text("\(result.metric) target: \(result.target.formatted())").font(.caption.monospaced()).foregroundStyle(Studio.muted)
                        Spacer()
                        Button("Review & approve deployment") { showApproval = true }.buttonStyle(.bordered).disabled(model.busy || labelsEdited)
                    }.panel()
                    if result.metric == "text_accuracy" { ReadingEvaluationDetails(evaluation: result) }
                    EvaluationQualityView(result: result)
                    if let warnings = result.warnings { ForEach(warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) } }
                    if !result.failures.isEmpty {
                        VStack(alignment: .leading, spacing: 9) { Eyebrow(text: "Worst failures first")
                            ForEach(Array(result.failures.prefix(5).enumerated()), id: \.offset) { _, failure in
                                Text(failure.object.keys.sorted().map { "\($0): \(failure.object[$0]?.display ?? "")" }.joined(separator: " · ")).font(.caption).textSelection(.enabled)
                            }
                        }.panel()
                    }
                }
                if let current {
                    HStack(alignment: .top, spacing: 20) {
                        VStack(alignment: .leading, spacing: 14) {
                            HStack { Eyebrow(text: "Ground truth editor"); Spacer(); Text("Drag to draw a box").font(.caption).foregroundStyle(Studio.muted) }
                            ImageCanvas(path: model.resolveImagePath(current.imagePath), detections: current.detections, onDraw: { box in
                                guard model.dataset?.annotations.indices.contains(annotationIndex) == true else { return }
                                model.dataset?.annotations[annotationIndex].detections.append(Detection(label: label, confidence: 1, box: box))
                                model.dataset?.annotations[annotationIndex].reviewed = false; labelsEdited = true
                            }).frame(height: 340)
                            HStack {
                                Button { annotationIndex = max(0, annotationIndex-1) } label: { Image(systemName: "chevron.left") }.disabled(annotationIndex == 0)
                                Text("Image \(annotationIndex+1) / \(model.dataset?.annotations.count ?? 0)").font(.caption.monospaced())
                                Button { annotationIndex = min((model.dataset?.annotations.count ?? 1)-1, annotationIndex+1) } label: { Image(systemName: "chevron.right") }.disabled(annotationIndex >= (model.dataset?.annotations.count ?? 1)-1)
                                Spacer()
                                Toggle("Reviewed", isOn: Binding(get: { self.current?.reviewed ?? false }, set: { model.dataset?.annotations[annotationIndex].reviewed = $0; labelsEdited = true })).toggleStyle(.checkbox)
                            }
                        }.frame(maxWidth: .infinity).panel()
                        VStack(alignment: .leading, spacing: 14) {
                            Eyebrow(text: "Labels")
                            if EvaluationPresentation.isReading(model.candidate) {
                                ExpectedTextEditor(values: current.expectedTexts) { values in
                                    guard let annotation = self.current else { return }
                                    model.dataset?.annotations[annotationIndex] = ExpectedTextEditing.update(annotation, values: values); labelsEdited = true
                                }.id(current.imagePath)
                            }
                            TextField("Object label", text: $label).textFieldStyle(.roundedBorder)
                            Text("Draw a tight box around each object. Remove incorrect boxes, then mark the image reviewed.").font(.caption).foregroundStyle(Studio.muted)
                            ForEach(Array(current.detections.enumerated()), id: \.offset) { index, detection in
                                HStack { Text(detection.label).font(.callout); Spacer(); Button { model.dataset?.annotations[annotationIndex].detections.remove(at: index); model.dataset?.annotations[annotationIndex].reviewed = false; labelsEdited = true } label: { Image(systemName: "trash") }.buttonStyle(.plain).foregroundStyle(Studio.muted) }
                            }
                            Divider()
                            Text("\(model.dataset?.annotations.filter(\.reviewed).count ?? 0) of \(model.dataset?.annotations.count ?? 0) images reviewed").font(.caption).foregroundStyle(Studio.muted)
                            if model.project?.fixture == true { Text("Synthetic walkthrough labels are generated with the fixture images. These scores are plumbing checks, not field accuracy.").font(.caption).foregroundStyle(.orange) }
                            Spacer()
                        }.frame(width: 220).panel()
                    }
                } else { EmptyCard(symbol: "checkmark.rectangle.stack", title: "Import samples to label", detail: "Evaluation uses reviewed labels and the current candidate. Imported images remain unreviewed until you confirm them.").frame(height: 300).panel() }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }.task { try? await model.loadEvidence() }
        .sheet(isPresented: $showApproval) { DeploymentApprovalSheet { showApproval = false } }
    }

}

