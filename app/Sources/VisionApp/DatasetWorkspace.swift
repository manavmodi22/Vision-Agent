import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class DatasetWorkspace: ObservableObject {
    @Published var manifest: DatasetManifest?
    @Published var activeImageID: String?
    @Published var annotation: Annotation?
    @Published var selectedBox: Int?
    @Published var selectedTextRegionID: String?
    @Published var labelMode = AnnotationLabelMode.objects
    @Published var showReadingPredictions = true
    private var labelModeChosen = false
    @Published var activeClass = ""
    @Published var tool = AnnotationTool.select
    @Published var zoom: Double = 1
    @Published var fitToken = 0
    @Published var showPredictions = false
    @Published var error: String?
    @Published var notice: String?
    @Published var loading = false
    @Published var saving = false
    @Published var hasConflict = false
    @Published var versions: [JSONValue] = []
    @Published var holdoutSelection: Set<String> = []
    @Published var search = ""
    @Published var filter = DatasetFilter.all
    @Published private(set) var undoStack: [Annotation] = []
    @Published private(set) var redoStack: [Annotation] = []
    @Published private(set) var savedAnnotation: Annotation?
    let projectID: String
    let client: EngineClient
    private var saveTask: Task<Void, Never>?
    private var route: String { "/projects/\(projectID)/dataset" }
    init(projectID: String, client: EngineClient) { self.projectID = projectID; self.client = client }
    var classes: [DatasetClass] { manifest?.classes ?? [] }
    var images: [DatasetImage] { manifest?.images ?? [] }
    var activeImage: DatasetImage? { images.first { $0.id == activeImageID } }
    var isDirty: Bool { annotation != savedAnnotation }
    var saveStatus: String { hasConflict ? "Save conflict · draft preserved" : saving ? "Saving…" : isDirty ? "Unsaved changes" : "All changes saved" }
    var colors: [String: String] { Dictionary(uniqueKeysWithValues: classes.map { ($0.name, $0.color) }) }
    var filteredImages: [DatasetImage] {
        images.filter { image in
            let matches = search.isEmpty || image.filename.localizedCaseInsensitiveContains(search)
            switch filter {
            case .all: return matches
            case .unreviewed: return matches && !image.reviewed
            case .reviewed: return matches && image.reviewed
            case .empty: return matches && image.annotationCount == 0 && (image.textRegionCount ?? 0) == 0
            }
        }
    }
    func load() async {
        guard !loading, await saveNow() else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            let previousRevision = manifest?.revision
            manifest = try await client.request("GET", route)
            if let id = activeImageID, previousRevision != manifest?.revision {
                let current: ImageAnnotationResponse = try await client.request("GET", route + "/images/\(id)")
                annotation = current.annotation; savedAnnotation = current.annotation
                manifest?.revision = current.revision; selectedBox = nil; selectedTextRegionID = nil; undoStack = []; redoStack = []
            }
            versions = try await client.request("GET", route + "/versions")
            if !classes.contains(where: { $0.name == activeClass }) { activeClass = classes.first?.name ?? "" }
        } catch { self.error = error.localizedDescription }
    }
    func openImage(_ id: String) async {
        guard !loading else { return }
        guard await saveNow() else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            let result: ImageAnnotationResponse = try await client.request("GET", route + "/images/\(id)")
            manifest?.revision = result.revision; activeImageID = id
            annotation = result.annotation; savedAnnotation = result.annotation
            selectedBox = nil; selectedTextRegionID = nil; undoStack = []; redoStack = []; hasConflict = false
            zoom = 1; fitToken += 1
        } catch { self.error = error.localizedDescription }
    }
    func returnToGrid() async {
        guard await saveNow() else { return }
        activeImageID = nil; annotation = nil; savedAnnotation = nil; selectedBox = nil; selectedTextRegionID = nil
    }
    func reloadSavedImage() async {
        guard let id = activeImageID else { return }
        // This is called only after the user explicitly chooses to discard the draft.
        saveTask?.cancel(); annotation = savedAnnotation; hasConflict = false
        await load(); await openImage(id)
    }
    func change(_ updated: Annotation) {
        let updated = TextRegionEditing.projected(updated)
        guard let current = annotation, current != updated, !hasConflict else { return }
        undoStack.append(current); if undoStack.count > 100 { undoStack.removeFirst() }
        redoStack = []; annotation = updated; scheduleSave()
    }
    func editBoxes(_ boxes: [Detection]) {
        guard var updated = annotation, updated.detections != boxes else { return }
        updated.detections = boxes; updated.reviewed = false; change(updated)
    }
    func createBox(_ box: [Double]) {
        guard var updated = annotation, !activeClass.isEmpty else { error = "Add or select a class before drawing a box."; return }
        updated.detections.append(Detection(label: activeClass, confidence: 1, box: box))
        updated.reviewed = false; change(updated); selectedBox = updated.detections.count-1; tool = .select
    }
    func reassign(_ label: String) {
        activeClass = label
        guard var updated = annotation, let index = selectedBox, updated.detections.indices.contains(index), updated.detections[index].label != label else { return }
        updated.detections[index].label = label; updated.reviewed = false; change(updated)
    }
    func deleteSelected() {
        guard var updated = annotation, let index = selectedBox, updated.detections.indices.contains(index) else { return }
        updated.detections.remove(at: index); updated.reviewed = false; change(updated); selectedBox = nil
    }
    func acceptPrediction(_ prediction: Detection) {
        guard var updated = annotation, classes.contains(where: { $0.name == prediction.label }) else { error = "Add the prediction class to the dataset before accepting it."; return }
        var label = prediction; label.confidence = 1
        updated.detections.append(label); updated.reviewed = false; change(updated); selectedBox = updated.detections.count-1
    }
    func editExpectedTexts(_ values: [String]) {
        guard let annotation, annotation.expectedTextSource == "manual" else { return }
        change(ExpectedTextEditing.update(annotation, values: values))
    }
    func setReviewed(_ reviewed: Bool) {
        guard var updated = annotation else { return }
        guard !reviewed || (!isDirty && !saving) else { error = "Wait for pending edits to save before marking this image reviewed."; return }
        guard !reviewed || TextRegionEditing.isComplete(updated) else { error = "Transcribe every text region before marking this image reviewed. Empty transcripts remain drafts."; return }
        updated.reviewed = reviewed; change(updated)
    }
    func undo() {
        guard !hasConflict, let previous = undoStack.popLast(), let current = annotation else { return }
        redoStack.append(current); annotation = TextRegionEditing.restoring(previous, from: current); selectedBox = nil; selectedTextRegionID = nil; scheduleSave()
    }
    func redo() {
        guard !hasConflict, let next = redoStack.popLast(), let current = annotation else { return }
        undoStack.append(current); annotation = TextRegionEditing.restoring(next, from: current); selectedBox = nil; selectedTextRegionID = nil; scheduleSave()
    }
    func navigate(_ offset: Int) {
        guard let id = activeImageID, let index = filteredImages.firstIndex(where: { $0.id == id }), filteredImages.indices.contains(index+offset) else { return }
        let next = filteredImages[index+offset].id
        Task { await openImage(next) }
    }
    func command(_ command: String) {
        switch command {
        case "v": tool = .select
        case "b": tool = .box
        case "h": tool = .pan
        case "f": zoom = 1; fitToken += 1
        case "+", "=": zoom = min(12, zoom*1.25)
        case "-": zoom = max(0.25, zoom/1.25)
        case "delete": if labelMode == .textRegions { deleteTextRegion() } else { deleteSelected() }
        case "undo": undo()
        case "redo": redo()
        case "next": navigate(1)
        case "previous": navigate(-1)
        case "cancel": selectedBox = nil; selectedTextRegionID = nil
        default: break
        }
    }
    private func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            do { try await Task.sleep(for: .milliseconds(650)) } catch { return }
            guard let self, !Task.isCancelled else { return }
            _ = await self.saveNow()
        }
    }
    @discardableResult
    func saveNow() async -> Bool {
        guard !hasConflict, !Task.isCancelled else { return false }
        while saving {
            do { try await Task.sleep(for: .milliseconds(40)) } catch { return false }
        }
        guard isDirty, let id = activeImageID, let draft = annotation, let revision = manifest?.revision else { return true }
        saving = true; error = nil
        defer { saving = false }
        do {
            let request = ImageAnnotationRequest(baseRevision: revision, annotation: draft)
            let result = try await client.send("PUT", route + "/images/\(id)", value: request, as: ImageAnnotationResponse.self)
            manifest?.revision = result.revision; savedAnnotation = result.annotation
            if annotation == draft { annotation = result.annotation }
            if let index = manifest?.images.firstIndex(where: { $0.id == id }) {
                manifest?.images[index].reviewed = result.annotation.reviewed
                manifest?.images[index].annotationCount = result.annotation.detections.count
                manifest?.images[index].textRegionCount = result.annotation.textRegions.count
            }
            saving = false
            if isDirty { return await saveNow() }
            return true
        } catch EngineError.server(409, let message) {
            hasConflict = true; error = "\(message) Your unsaved annotation remains on screen. Reload saved labels only when you are ready to discard it."; return false
        } catch { self.error = error.localizedDescription; return false }
    }
    func configureLabelMode(reading: Bool) {
        if !labelModeChosen { labelMode = reading ? .textRegions : .objects }
    }
    func chooseLabelMode(_ mode: AnnotationLabelMode) {
        labelModeChosen = true; labelMode = mode; selectedBox = nil; selectedTextRegionID = nil; tool = .select
    }
    func saveClasses(_ updated: [DatasetClass]) async {
        guard await saveNow(), let revision = manifest?.revision else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            manifest = try await client.send("PUT", route + "/classes", value: DatasetClassesRequest(baseRevision: revision, classes: updated), as: DatasetManifest.self)
            if !classes.contains(where: { $0.name == activeClass }) { activeClass = classes.first?.name ?? "" }
            if let id = activeImageID {
                let image: ImageAnnotationResponse = try await client.request("GET", route + "/images/\(id)")
                annotation = image.annotation; savedAnnotation = image.annotation; manifest?.revision = image.revision
                undoStack = []; redoStack = []
            }
        } catch { self.error = error.localizedDescription }
    }
    func snapshot(_ name: String) async {
        guard await saveNow() else { return }
        do {
            let _: JSONValue = try await client.request("POST", route + "/versions", body: ["name": .string(name)])
            versions = try await client.request("GET", route + "/versions")
            notice = "Dataset snapshot saved: \(name)"
        } catch { self.error = error.localizedDescription }
    }
    func setHoldout() async {
        guard await saveNow(), (10...50).contains(holdoutSelection.count) else { return }
        loading = true; error = nil
        defer { loading = false }
        do {
            manifest = try await client.request("POST", route + "/holdout", body: ["image_ids": .array(holdoutSelection.sorted().map(JSONValue.string))])
            holdoutSelection = []; notice = "Validation set saved. These images are excluded from training."
        } catch { self.error = error.localizedDescription }
    }
    func exportCOCO() async {
        guard await saveNow() else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "annotations.coco.json"; panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { try await client.rawRequest("GET", route + "/export-coco").write(to: url); notice = "COCO annotations exported." }
        catch { self.error = error.localizedDescription }
    }
    func importCOCO() async {
        guard await saveNow() else { return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        loading = true; error = nil
        do {
            let _: JSONValue = try await client.request("POST", route + "/import-coco", body: ["path": .string(url.path), "replace_existing": .bool(false)])
            activeImageID = nil; annotation = nil; savedAnnotation = nil
            loading = false; await load(); notice = "COCO annotations imported without replacing existing labels."
        } catch { self.error = error.localizedDescription; loading = false }
    }
}
