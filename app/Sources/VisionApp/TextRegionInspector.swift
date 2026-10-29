import SwiftUI

struct TextRegionInspector: View {
    @ObservedObject var store: DatasetWorkspace
    @NativeState<Bool> private var projectionSheet = false
    private var selected: TextRegion? { store.annotation?.textRegions.first { $0.id == store.selectedTextRegionID } }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text("Text regions").font(.headline); Spacer(); Text("\(store.annotation?.textRegions.count ?? 0)").font(.caption.monospaced()).foregroundStyle(Studio.muted) }
                Text("Draw a rectangle, then move its corners to fit the text. Saved labels use solid purple outlines.").font(.caption).foregroundStyle(Studio.muted)
                Button { store.tool = .box } label: { Label("Draw text region", systemImage: "rectangle.dashed") }
                if store.annotation?.textRegions.isEmpty == true { Text("No saved text regions. Model predictions stay separate until you explicitly copy one.").font(.caption).foregroundStyle(Studio.muted) }
                ScrollView {
                LazyVStack(spacing: 4) {
                ForEach(Array((store.annotation?.textRegions ?? []).enumerated()), id: \.element.id) { index, region in
                    Button { store.selectedTextRegionID = region.id; store.tool = .select } label: {
                        HStack(alignment: .top) {
                            Text("\(index+1)").font(.caption.monospaced())
                            Text(region.transcript?.isEmpty == false ? region.transcript! : "Untranscribed draft").font(.caption).lineLimit(2)
                            Spacer(minLength: 0)
                            if region.transcript?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false { Image(systemName: "pencil.circle").foregroundStyle(.orange) }
                        }.padding(7).frame(maxWidth: .infinity, alignment: .leading)
                            .background(selected?.id == region.id ? Studio.raised : .clear).clipShape(RoundedRectangle(cornerRadius: 5))
                    }.buttonStyle(.plain)
                }
                }
                }.frame(height: min(180, CGFloat(store.annotation?.textRegions.count ?? 0)*46))
                if let selected {
                    Divider()
                    Text("Transcript").font(.headline)
                    TextField("Enter the exact visible text", text: Binding(get: { selected.transcript ?? "" }, set: { store.editTranscript(id: selected.id, value: $0) }), axis: .vertical)
                        .font(.system(size: 13, design: .monospaced)).lineLimit(2...6).textFieldStyle(.roundedBorder)
                    DisclosureGroup("Unicode code points") {
                        Text(ReadingPresentation.codePoints(selected.transcript ?? "")).font(.caption2.monospaced()).textSelection(.enabled)
                    }.font(.caption2)
                    Text("Text is saved exactly as typed. Editing text or geometry clears review.").font(.caption2).foregroundStyle(Studio.muted)
                    if let seed = selected.seed {
                        DisclosureGroup("Copied prediction provenance") {
                            Text("\(seed.modelID) · \(seed.adapterID)\nOriginal value: \(seed.observation.text)\nIdentity: \(seed.identityHash)").font(.caption2.monospaced()).textSelection(.enabled)
                            Text("The source prediction is retained separately from this edited label.").font(.caption2).foregroundStyle(Studio.muted)
                        }.font(.caption2)
                    }
                    Button("Delete text region", role: .destructive) { store.deleteTextRegion() }
                }
                Divider()
                Toggle("Show reader predictions", isOn: $store.showReadingPredictions).toggleStyle(.checkbox).font(.caption)
                Text("Dashed cyan regions are model evidence. Copying creates unreviewed labels; it does not run a reader.").font(.caption2).foregroundStyle(Studio.muted)
                Divider()
                if let annotation = store.annotation {
                    if annotation.expectedTextSource == "regions" {
                        Text("Image-level expected values").font(.headline)
                        Text("Derived from region transcripts").font(.caption).foregroundStyle(Studio.accent)
                        ForEach(Array(annotation.expectedTexts.enumerated()), id: \.offset) { _, value in Text(value).font(.caption.monospaced()).textSelection(.enabled) }
                        if annotation.expectedTexts.isEmpty { Text("No expected values.").font(.caption).foregroundStyle(Studio.muted) }
                        Button("Edit values separately") { store.setExpectedTextSource("manual") }.font(.caption)
                    } else {
                        ExpectedTextEditor(values: annotation.expectedTexts, onChange: store.editExpectedTexts).id(annotation.imagePath)
                        Button("Use region transcripts for evaluation…") { projectionSheet = true }
                            .font(.caption).disabled(!TextRegionEditing.isComplete(annotation))
                    }
                    Text("Current scores compare image-level text values, not region locations or reading order. Region projection preserves repeated values, while current workflow output deduplicates them; repeated text can therefore fail the existing text metric.").font(.caption2).foregroundStyle(Studio.muted)
                    if !TextRegionEditing.isComplete(annotation) { Text("Complete every transcript before marking this image reviewed or using region values.").font(.caption).foregroundStyle(.orange) }
                }
            }.padding(16)
        }.background(Studio.panel)
            .sheet(isPresented: $projectionSheet) { projectionReview }
    }
    private var projectionReview: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Use region transcripts for image-level evaluation?").font(.title3.weight(.semibold))
            Text("This replaces the image-level expected values and keeps them linked to future region edits. It clears review. Geometry is saved, but current evaluation scores only image-level text.").font(.callout).foregroundStyle(Studio.muted)
            HStack(alignment: .top, spacing: 24) {
                valuesColumn("Current values", values: store.annotation?.expectedTexts ?? [])
                valuesColumn("Proposed values", values: TextRegionEditing.projection(store.annotation?.textRegions ?? []))
            }
            HStack { Button("Cancel") { projectionSheet = false }; Spacer(); Button("Use region transcripts") { store.setExpectedTextSource("regions"); projectionSheet = false }.buttonStyle(.borderedProminent).disabled(store.annotation.map { !TextRegionEditing.isComplete($0) } ?? true) }
        }.padding(24).frame(width: 580)
    }
    private func valuesColumn(_ title: String, values: [String]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            ScrollView { VStack(alignment: .leading, spacing: 5) {
                if values.isEmpty { Text("No expected values (negative example)").font(.caption).foregroundStyle(Studio.muted) }
                ForEach(Array(values.enumerated()), id: \.offset) { _, value in Text(value).font(.caption.monospaced()).textSelection(.enabled) }
            }.frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 150)
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
