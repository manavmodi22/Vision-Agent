import SwiftUI

struct ExpectedTextEditor: View {
    let values: [String]
    let onChange: ([String]) -> Void
    @NativeState<String> private var draft = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Expected text / barcodes").font(.headline)
            Text("Enter each exact value on its own line. Leave empty when the image contains no expected text or code.").font(.caption).foregroundStyle(Studio.muted)
            TextEditor(text: $draft).font(.system(size: 12, design: .monospaced)).scrollContentBackground(.hidden)
                .padding(6).frame(minHeight: 130).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 6))
            Text("Editing clears review. Check the image before marking it reviewed again.").font(.caption2).foregroundStyle(Studio.muted)
        }
        .onAppear { draft = values.joined(separator: "\n") }
        .onChange(of: draft) { _, text in let parsed = ExpectedTextEditing.values(text); if parsed != values { onChange(parsed) } }
        .onChange(of: values) { _, updated in if ExpectedTextEditing.values(draft) != updated { draft = updated.joined(separator: "\n") } }
    }
}
