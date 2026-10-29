import SwiftUI

struct AnnotationInspector: View {
    @ObservedObject var store: DatasetWorkspace
    let predictions: [Detection]
    let editClasses: () -> Void
    var readingTask = false
    var supportsObjects = true
    private var selected: Detection? {
        guard let index = store.selectedBox, let boxes = store.annotation?.detections, boxes.indices.contains(index) else { return nil }
        return boxes[index]
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if readingTask, let annotation = store.annotation {
                    ExpectedTextEditor(values: annotation.expectedTexts, onChange: store.editExpectedTexts).id(annotation.imagePath)
                    if annotation.proposal != nil && !annotation.reviewed { Text("Model proposal provenance is retained. This image still needs human review.").font(.caption2).foregroundStyle(.orange) }
                    Divider()
                }
                if !readingTask || supportsObjects {
                HStack { Text("Class").font(.headline); Spacer(); Button(action: editClasses) { Image(systemName: "plus") } }
                if store.classes.isEmpty { Text("Add a class to draw objects.").font(.caption).foregroundStyle(.orange) }
                else {
                    Picker("Class", selection: Binding(get: { selected?.label ?? store.activeClass }, set: store.reassign)) {
                        ForEach(store.classes) { item in Text(item.name).tag(item.name) }
                    }.labelsHidden()
                }
                HStack { Text("Objects").font(.headline); Spacer(); Text("\(store.annotation?.detections.count ?? 0)").font(.caption.monospaced()).foregroundStyle(Studio.muted) }
                if store.annotation?.proposal != nil && store.annotation?.reviewed == false {
                    Text("Model proposals · not reviewed").font(.caption).foregroundStyle(.orange)
                }
                ForEach(Array((store.annotation?.detections ?? []).enumerated()), id: \.offset) { index, detection in
                    Button {
                        store.selectedBox = index; store.activeClass = detection.label; store.tool = .select
                    } label: {
                        HStack(spacing: 8) {
                            Circle().fill(Color(nsColor: NSColor(hex: store.colors[detection.label] ?? "#5BD6C0"))).frame(width: 8, height: 8)
                            Text(detection.label).font(.callout).lineLimit(1)
                            Spacer(); Text("\(index+1)").font(.caption.monospaced()).foregroundStyle(Studio.muted)
                        }.padding(8).background(index == store.selectedBox ? Studio.raised : .clear).clipShape(RoundedRectangle(cornerRadius: 5))
                    }.buttonStyle(.plain)
                }
                if let selected {
                    Divider()
                    Text("Selected box").font(.headline)
                    if selected.box.count == 4, let image = store.activeImage {
                        let box = selected.box
                        Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 7) {
                            GridRow { Text("X"); Text("\(Int(box[0]*Double(image.width))) px") }
                            GridRow { Text("Y"); Text("\(Int(box[1]*Double(image.height))) px") }
                            GridRow { Text("Width"); Text("\(Int((box[2]-box[0])*Double(image.width))) px") }
                            GridRow { Text("Height"); Text("\(Int((box[3]-box[1])*Double(image.height))) px") }
                        }.font(.caption.monospaced()).foregroundStyle(Studio.muted)
                    }
                    Button(role: .destructive) { store.deleteSelected() } label: { Label("Delete object", systemImage: "trash") }
                    Text("Drag a box to move it. Drag a square handle to resize. Class changes apply to the selected object.").font(.caption).foregroundStyle(Studio.muted)
                }
                Divider()
                Text("Predictions").font(.headline)
                Toggle("Show read-only overlay", isOn: $store.showPredictions).toggleStyle(.checkbox).font(.caption)
                Text("Labels use solid outlines. Preview predictions use dashed orange outlines and never save automatically.").font(.caption).foregroundStyle(Studio.muted)
                if predictions.isEmpty { Text("Run a workflow preview to compare predictions on this image.").font(.caption).foregroundStyle(Studio.muted) }
                ForEach(Array(predictions.enumerated()), id: \.offset) { _, prediction in
                    HStack { VStack(alignment: .leading, spacing: 3) { Text(prediction.label).font(.caption); Text(String(format: "%.0f%% confidence", prediction.confidence*100)).font(.system(size: 10)).foregroundStyle(Studio.muted) }; Spacer(); Button { store.acceptPrediction(prediction) } label: { Image(systemName: "plus") }.help("Copy this prediction into unreviewed labels") }
                }
                }
                Divider()
                Text("Review").font(.headline)
                Text(readingTask ? "Check the expected values against the image before marking it reviewed. Editing text or boxes clears review." : store.annotation?.reviewed == true ? "This image is marked reviewed. Editing a box clears that review." : "Check every visible object before marking this image reviewed. Empty images can be reviewed as negative examples.").font(.caption).foregroundStyle(Studio.muted)
            }.padding(16)
        }.background(Studio.panel)
    }
}

struct DatasetClassEditor: View {
    @Environment(\.dismiss) private var dismiss
    @NativeState<DatasetClass> private var item: DatasetClass
    let existing: Bool
    let onSave: (DatasetClass) -> Void
    let onDelete: () -> Void
    let palette = ["#43C6AC", "#609CFF", "#E8B86D", "#BF8CF2", "#F1849C", "#66CCD9"]
    init(item: DatasetClass, existing: Bool, onSave: @escaping (DatasetClass) -> Void, onDelete: @escaping () -> Void) {
        _item = NativeState(initialValue: item); self.existing = existing; self.onSave = onSave; self.onDelete = onDelete
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(existing ? "Edit class" : "Add class").font(.title3.weight(.semibold))
            TextField("Class name", text: $item.name).textFieldStyle(.roundedBorder)
            HStack(spacing: 12) { ForEach(palette, id: \.self) { color in Button { item.color = color } label: { Circle().fill(Color(nsColor: NSColor(hex: color))).frame(width: 26, height: 26).overlay(Circle().stroke(item.color == color ? .white : .clear, lineWidth: 2)) }.buttonStyle(.plain) } }
            if existing { Text("Renaming updates labels in this class. A class with labelled objects cannot be deleted.").font(.caption).foregroundStyle(Studio.muted) }
            HStack {
                if existing { Button("Delete", role: .destructive) { dismiss(); onDelete() } }
                Button("Cancel") { dismiss() }; Spacer()
                Button("Save class") { item.name = item.name.trimmingCharacters(in: .whitespacesAndNewlines); onSave(item); dismiss() }.buttonStyle(.borderedProminent).disabled(item.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.padding(26).frame(width: 390)
    }
}
