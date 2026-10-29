import SwiftUI

struct ExpectedTextEditor: View {
    let values: [String]
    let onChange: ([String]) -> Void
    @NativeState<String> private var draft = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Expected text / barcodes").font(.headline)
            Text("Enter each exact value on its own line. Leave empty when the image contains no expected text or code.").font(.caption).foregroundStyle(Studio.muted)
            TextEditor(text: Binding(get: { draft }, set: { text in
                draft = text
                let parsed = ExpectedTextEditing.values(text)
                if !ExpectedTextEditing.same(parsed, values) { onChange(parsed) }
            })).font(.system(size: 12, design: .monospaced)).scrollContentBackground(.hidden)
                .padding(6).frame(minHeight: 130).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 6))
            Text("Editing clears review. Check the image before marking it reviewed again.").font(.caption2).foregroundStyle(Studio.muted)
            Text("Expected values are image-level labels. Reader regions and confidence remain model evidence; region geometry and reading order are not scored.").font(.caption2).foregroundStyle(Studio.muted)
        }
        .onAppear { draft = values.joined(separator: "\n") }
        .onChange(of: values.map { Data($0.utf8) }) { _, _ in
            if !ExpectedTextEditing.same(ExpectedTextEditing.values(draft), values) { draft = values.joined(separator: "\n") }
        }
    }
}
