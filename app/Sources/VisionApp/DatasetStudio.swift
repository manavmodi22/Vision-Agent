import SwiftUI

struct DatasetStudio: View {
    @EnvironmentObject var workspace: WorkspaceModel
    @StateObject private var store: DatasetWorkspace
    @NativeState<DatasetClass?> private var editingClass: DatasetClass?
    @NativeState<Bool> private var snapshotSheet = false
    @NativeState<Bool> private var holdoutSheet = false
    @NativeState<Bool> private var reloadSheet = false
    @NativeState<String> private var snapshotName = ""
    private let onContinue: (() -> Void)?
    init(store: DatasetWorkspace, onContinue: (() -> Void)? = nil) { _store = StateObject(wrappedValue: store); self.onContinue = onContinue }
    private var readingTask: Bool { EvaluationPresentation.isReading(workspace.candidate) }
    private var objectTask: Bool { EvaluationPresentation.hasDetector(workspace.candidate) }
    private var predictions: [Detection] {
        guard let image = store.activeImage else { return [] }
        return workspace.preview?.frames.first(where: { $0.imagePath == image.imagePath || URL(fileURLWithPath: $0.imagePath).lastPathComponent == image.filename })?.detections ?? []
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack { Text(readingTask ? "Review the expected text or barcode values, then continue the build." : "Review the agent’s proposed labels, then continue the build.").font(.caption).foregroundStyle(Studio.muted); Spacer(); Button("Continue building") { if let onContinue { onContinue() } else { workspace.returnToAgent() } }.buttonStyle(.borderedProminent).disabled(store.saving || workspace.busy) }.padding(.horizontal, 24).padding(.vertical, 10)
            if let error = store.error { inlineMessage(error, color: .orange) }
            if let notice = store.notice { inlineMessage(notice, color: Studio.accent) }
            if store.activeImage != nil {
                annotationHeader
                HStack(spacing: 0) {
                    filmstrip.frame(width: 150)
                    Divider()
                    VStack(spacing: 0) {
                        canvasToolbar
                        if let image = store.activeImage, let annotation = store.annotation {
                            AnnotationCanvas(imagePath: image.imagePath, detections: annotation.detections,
                                predictions: store.showPredictions ? predictions : [], colors: store.colors,
                                selectedIndex: store.selectedBox, tool: store.tool, zoom: store.zoom, fitToken: store.fitToken,
                                onSelect: { index in store.selectedBox = index; if let index, annotation.detections.indices.contains(index) { store.activeClass = annotation.detections[index].label } },
                                onCreate: store.createBox, onEdit: store.editBoxes, onCommand: store.command,
                                onZoom: { store.zoom = $0 }).allowsHitTesting(!store.loading && !store.hasConflict)
                                .overlay(alignment: .bottomLeading) { Text("V Select  ·  B Box  ·  H Pan  ·  Space-drag Pan  ·  ← → Images  ·  ⌘Z Undo").font(.system(size: 10, design: .monospaced)).foregroundStyle(.white.opacity(0.65)).padding(8).background(.black.opacity(0.65)).allowsHitTesting(false) }
                        }
                    }
                    Divider()
                    AnnotationInspector(store: store, predictions: predictions, editClasses: { editingClass = DatasetClass(id: UUID().uuidString.lowercased(), name: "", color: "#5BD6C0") }, readingTask: readingTask, supportsObjects: objectTask).frame(width: 238).disabled(store.loading || store.hasConflict)
                }
            } else {
                gridHeader
                HStack(alignment: .top, spacing: 18) {
                    imageGrid.frame(maxWidth: .infinity, alignment: .leading)
                    if readingTask && !objectTask {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Text and barcode review").font(.headline)
                            Text("Open each example, enter its expected text or barcode values, and mark it reviewed after checking the image. No object classes are needed for this workflow.").font(.callout).foregroundStyle(Studio.muted)
                        }.padding(18).frame(width: 238).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 10))
                    } else { classPanel.frame(width: 238).disabled(store.loading) }
                }.padding(.horizontal, 24).padding(.bottom, 20)
            }
        }.task { await store.load() }
            .onChange(of: workspace.project?.media.count) { _, _ in Task { await store.load() } }
            .onChange(of: workspace.busy) { _, busy in if !busy && store.activeImageID == nil { Task { await store.load() } } }
            .sheet(item: $editingClass) { item in DatasetClassEditor(item: item, existing: store.classes.contains(where: { $0.id == item.id }), onSave: { updated in
                var classes = store.classes; if let index = classes.firstIndex(where: { $0.id == updated.id }) { classes[index] = updated } else { classes.append(updated) }
                Task { await store.saveClasses(classes) }
            }, onDelete: { Task { await store.saveClasses(store.classes.filter { $0.id != item.id }) } }) }
            .sheet(isPresented: $snapshotSheet) { snapshotDialog }
            .confirmationDialog("Set \(store.holdoutSelection.count) images as the validation set?", isPresented: $holdoutSheet, titleVisibility: .visible) {
                Button("Set validation images") { Task { await store.setHoldout() } }
            } message: { Text("Validation images are held out from training. Changing this set invalidates earlier evaluation evidence.") }
            .confirmationDialog("Discard this image's unsaved draft and reload saved labels?", isPresented: $reloadSheet, titleVisibility: .visible) {
                Button("Discard draft & reload", role: .destructive) { Task { await store.reloadSavedImage() } }
            }
    }
    private var gridHeader: some View {
        HStack(spacing: 12) {
            Text("\(store.images.count) images").font(.headline)
            Text("\(store.images.filter(\.reviewed).count) reviewed").font(.caption).foregroundStyle(Studio.muted)
            TextField("Search image names", text: $store.search).textFieldStyle(.roundedBorder).frame(maxWidth: 230)
            Picker("Status", selection: $store.filter) { ForEach(DatasetFilter.allCases, id: \.self) { Text($0.rawValue).tag($0) } }.labelsHidden().frame(width: 140)
            Spacer()
            if !store.holdoutSelection.isEmpty { Button("Validation (\(store.holdoutSelection.count))…") { holdoutSheet = true }.disabled(!(10...50).contains(store.holdoutSelection.count)) }
            Button("Suggest labels") { workspace.suggestLabels() }.disabled(!objectTask).help("Creates unreviewed proposals using the selected workflow. Reviewed labels are preserved.")
            Menu("Dataset") {
                Button("Refresh") { Task { await store.load() } }
                Button("Import COCO annotations…") { Task { await store.importCOCO() } }
                Button("Export COCO annotations…") { Task { await store.exportCOCO() } }
                Divider()
                Button("Save dataset version…") { snapshotName = "Revision \(store.manifest?.revision ?? 0)"; snapshotSheet = true }
                if !store.holdoutSelection.isEmpty { Button("Clear image selection") { store.holdoutSelection = [] } }
            }.fixedSize()
            Button("Import images…") { workspace.importMedia() }.buttonStyle(.borderedProminent)
        }.padding(.horizontal, 24).padding(.bottom, 16).disabled(store.loading || workspace.busy)
    }
    private var imageGrid: some View {
        ScrollView {
            if store.loading { ProgressView().padding(40) }
            else if store.filteredImages.isEmpty { Text(store.images.isEmpty ? "Import images or a recorded clip to begin annotating." : "No images match this filter.").font(.callout).foregroundStyle(Studio.muted).padding(40) }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 14)], alignment: .leading, spacing: 14) {
                ForEach(store.filteredImages) { image in
                    VStack(alignment: .leading, spacing: 8) {
                        Button { Task { await store.openImage(image.id) } } label: { DatasetThumbnail(path: image.imagePath).frame(height: 135).overlay(alignment: .topTrailing) { if image.reviewed { Image(systemName: "checkmark.circle.fill").foregroundStyle(Studio.accent).padding(7) } } }.buttonStyle(.plain)
                        Text(image.filename).font(.system(size: 11, weight: .medium)).lineLimit(1).help(image.filename)
                        HStack {
                            Toggle("Select", isOn: Binding(get: { store.holdoutSelection.contains(image.id) }, set: { if $0 { store.holdoutSelection.insert(image.id) } else { store.holdoutSelection.remove(image.id) } })).labelsHidden().toggleStyle(.checkbox)
                            Text("\(image.annotationCount) boxes · \(image.width)×\(image.height)").font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted)
                            Spacer(minLength: 0)
                        }
                        Text(image.split == "unassigned" ? (image.reviewed ? "Reviewed" : "Needs review") : image.split.capitalized).font(.system(size: 10)).foregroundStyle(image.split == "validation" ? .orange : Studio.muted)
                    }.padding(10).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8)).overlay(RoundedRectangle(cornerRadius: 8).stroke(store.holdoutSelection.contains(image.id) ? Studio.accent : .clear))
                }
            }
        }
    }
    private var classPanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack { Text("Classes").font(.headline); Spacer(); Button { editingClass = DatasetClass(id: UUID().uuidString.lowercased(), name: "", color: "#5BD6C0") } label: { Image(systemName: "plus") } }
                ForEach(store.classes) { item in
                    Button { editingClass = item } label: {
                        HStack { Circle().fill(Color(nsColor: NSColor(hex: item.color))).frame(width: 10, height: 10); Text(item.name).font(.callout); Spacer(); Image(systemName: "pencil").foregroundStyle(Studio.muted) }
                    }.buttonStyle(.plain)
                }
                if store.classes.isEmpty { Text("Add a class before drawing boxes.").font(.caption).foregroundStyle(Studio.muted) }
                Divider()
                Text("Dataset versions").font(.headline)
                Text("Revision \(store.manifest?.revision ?? 0)").font(.caption.monospaced()).foregroundStyle(Studio.muted)
                ForEach(Array(store.versions.prefix(10).enumerated()), id: \.offset) { _, version in
                    VStack(alignment: .leading, spacing: 4) { Text(version.object["name"]?.string ?? version.object["id"]?.string ?? "Snapshot").font(.caption); Text(version.object["created_at"]?.string ?? "").font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted) }
                }
                Text("Select 10–50 images in the grid to define a validation set excluded from training.").font(.caption).foregroundStyle(Studio.muted)
            }.padding(18).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }
    private var annotationHeader: some View {
        HStack(spacing: 14) {
            Button { Task { await store.returnToGrid() } } label: { Label("Dataset", systemImage: "chevron.left") }
            Text(store.activeImage?.filename ?? "").font(.system(size: 13, weight: .medium)).lineLimit(1)
            Text("\(store.activeImage?.width ?? 0) × \(store.activeImage?.height ?? 0)").font(.caption.monospaced()).foregroundStyle(Studio.muted)
            Spacer()
            if store.isDirty && !store.hasConflict { Button("Save now") { Task { await store.saveNow() } }.disabled(store.saving) }
            Text(store.saveStatus).font(.caption).foregroundStyle(store.hasConflict ? .orange : Studio.muted)
            if store.hasConflict { Button("Reload saved…") { reloadSheet = true } }
            Button { store.navigate(-1) } label: { Image(systemName: "chevron.left") }
            Button { store.navigate(1) } label: { Image(systemName: "chevron.right") }
            Toggle("Reviewed", isOn: Binding(get: { store.annotation?.reviewed ?? false }, set: store.setReviewed)).toggleStyle(.checkbox)
        }.padding(.horizontal, 20).padding(.bottom, 14).disabled(store.loading)
    }
    private var canvasToolbar: some View {
        HStack(spacing: 12) {
            Picker("Tool", selection: $store.tool) { Image(systemName: "cursorarrow").tag(AnnotationTool.select); Image(systemName: "rectangle.dashed").tag(AnnotationTool.box); Image(systemName: "hand.draw").tag(AnnotationTool.pan) }.pickerStyle(.segmented).frame(width: 150)
            Button { store.undo() } label: { Image(systemName: "arrow.uturn.backward") }.disabled(store.undoStack.isEmpty)
            Button { store.redo() } label: { Image(systemName: "arrow.uturn.forward") }.disabled(store.redoStack.isEmpty)
            Spacer()
            Button { store.command("-") } label: { Image(systemName: "minus.magnifyingglass") }
            Text("\(Int(store.zoom*100))%").font(.caption.monospaced()).frame(width: 42)
            Button { store.command("+") } label: { Image(systemName: "plus.magnifyingglass") }
            Button("Fit") { store.command("f") }
        }.padding(10).background(Studio.panel)
    }
    private var snapshotDialog: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Save dataset version").font(.title3.weight(.semibold))
            TextField("Version name", text: $snapshotName).textFieldStyle(.roundedBorder)
            Text("The snapshot includes image bytes, class definitions and labels at the current revision.").font(.caption).foregroundStyle(Studio.muted)
            HStack { Button("Cancel") { snapshotSheet = false }; Spacer(); Button("Save version") { snapshotSheet = false; Task { await store.snapshot(snapshotName) } }.buttonStyle(.borderedProminent).disabled(snapshotName.trimmingCharacters(in: .whitespaces).isEmpty) }
        }.padding(26).frame(width: 420)
    }
    private func inlineMessage(_ text: String, color: Color) -> some View {
        HStack { Text(text).font(.caption).textSelection(.enabled); Spacer(); Button { store.error = nil; store.notice = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }.foregroundStyle(color).padding(10).background(color.opacity(0.08)).padding(.horizontal, 24).padding(.bottom, 10)
    }
    private var filmstrip: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 10) {
                    ForEach(store.filteredImages) { image in
                        Button { Task { await store.openImage(image.id) } } label: {
                            VStack(alignment: .leading, spacing: 5) { DatasetThumbnail(path: image.imagePath).frame(height: 85); HStack { Text(image.filename).font(.system(size: 9)).lineLimit(1); if image.reviewed { Image(systemName: "checkmark.circle.fill").foregroundStyle(Studio.accent) } } }.padding(6).background(store.activeImageID == image.id ? Studio.accent.opacity(0.12) : .clear).clipShape(RoundedRectangle(cornerRadius: 6)).overlay(RoundedRectangle(cornerRadius: 6).stroke(store.activeImageID == image.id ? Studio.accent : .clear))
                        }.buttonStyle(.plain).id(image.id)
                    }
                }.padding(8)
            }.onChange(of: store.activeImageID) { _, id in if let id { proxy.scrollTo(id, anchor: .center) } }
        }
    }
}

struct DatasetThumbnail: View {
    let path: String
    var body: some View {
        Group { if let image = NSImage(contentsOfFile: path) { Image(nsImage: image).resizable().scaledToFit() } else { Image(systemName: "photo.badge.exclamationmark").foregroundStyle(Studio.muted) } }
            .frame(maxWidth: .infinity, maxHeight: .infinity).background(.black.opacity(0.3)).clipShape(RoundedRectangle(cornerRadius: 4))
    }
}
