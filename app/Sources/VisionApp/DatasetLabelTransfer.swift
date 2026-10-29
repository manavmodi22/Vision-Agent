import SwiftUI
import UniformTypeIdentifiers

extension DatasetWorkspace {
    func exportAllLabels() async {
        guard await saveNow() else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "annotations.vision-labels.json"; panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try await client.rawRequest("GET", "/projects/\(projectID)/dataset/export-labels").write(to: url)
            notice = "All labels exported. The JSON contains label data; transfer the matching images separately."
        } catch { self.error = error.localizedDescription }
    }
    func importAllLabels() async {
        guard await saveNow(), let revision = manifest?.revision else { return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        panel.message = "Choose a .vision-labels.json file. Matching images must already be imported into this project."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let review = NSAlert(); review.messageText = "Import labels from \(url.lastPathComponent)?"
        review.informativeText = "The engine verifies image pixel hashes. The archive includes object boxes, text regions and expected values, but no images. Imported labels need review in this project. Preserve existing labels unless you explicitly choose to replace them."
        review.addButton(withTitle: "Preserve existing labels")
        review.addButton(withTitle: "Cancel")
        review.addButton(withTitle: "Replace existing labels")
        let choice = review.runModal()
        guard choice == .alertFirstButtonReturn || choice == .alertThirdButtonReturn else { return }
        loading = true; error = nil
        do {
            let _: DatasetManifest = try await client.request("POST", "/projects/\(projectID)/dataset/import-labels", body: [
                "path": .string(url.path), "base_revision": .number(Double(revision)), "replace_existing": .bool(choice == .alertThirdButtonReturn)])
            await returnToGrid(); loading = false; await load()
            notice = "Labels imported. Imported labels need review in this project."
        } catch { self.error = error.localizedDescription; loading = false }
    }
}
