import AppKit

enum TextRegionChecks {
    @MainActor static func run() throws -> Int {
        var checks = 0
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw EngineError.protocolError("Text-region check failed: " + message) }; checks += 1
        }
        let quad = [[0.1,0.2],[0.7,0.1],[0.8,0.5],[0.2,0.6]]
        try require(TextRegionGeometry.valid(quad) && TextRegionGeometry.valid(Array(quad.reversed())), "clockwise and counterclockwise convex quads are valid")
        try require(!TextRegionGeometry.valid([[0,0],[1,1],[0,1],[1,0]]) && !TextRegionGeometry.valid([[0,0],[0.5,0],[1,0],[0,1]]), "crossed and collinear quads are rejected")
        let moved = TextRegionGeometry.move(quad, dx: 5, dy: -5)
        try require(TextRegionGeometry.valid(moved) && abs(moved[0][0]-0.3) < 1e-9 && moved[1][1] == 0, "moving a skewed quad clamps the whole shape without flattening")
        let corner = TextRegionGeometry.moveCorner(quad, index: 0, dx: 0.02, dy: 0.03)
        try require(abs(corner[0][0]-0.12) < 1e-9 && corner[1] == quad[1], "corner edits change only the selected point")
        try require(TextRegionGeometry.moveCorner(quad, index: 0, dx: 1, dy: 1) == quad, "a corner cannot invert or self-intersect the polygon")
        let region = TextRegion(id: "text-1", polygon: quad, box: ReadingGeometry.envelope(quad)!, transcript: "XХ", seed: nil)
        var tooLong = region; tooLong.transcript = String(repeating: "X", count: 16385)
        try require(TextRegionEditing.validationError([tooLong]) != nil && TextRegionEditing.validationError([region, region]) != nil, "oversized transcripts and duplicate IDs cannot become an unsavable native draft")
        var annotation = Annotation(imagePath: "/tmp/image.png", detections: [], reviewed: true, expectedTexts: ["manual"], proposal: .object(["source": .string("model_proposal")]), textRegions: [region])
        var changed = region; changed.transcript = "é"
        var decomposed = changed; decomposed.transcript = "e\u{301}"
        try require(changed != decomposed, "canonical Unicode equivalents remain distinct literal transcript edits")
        let edited = TextRegionEditing.replacing(annotation, regions: [changed])
        try require(!edited.reviewed && edited.expectedTexts == ["manual"] && edited.proposal == annotation.proposal, "region changes clear review but preserve manual values and image provenance")
        annotation.expectedTextSource = "regions"
        let duplicate = TextRegion(id: "text-2", polygon: quad, box: region.box, transcript: "XХ", seed: nil)
        let projection = TextRegionEditing.replacing(annotation, regions: [region, duplicate])
        try require(projection.expectedTexts == ["XХ","XХ"] && projection.textRegions.count == 2, "region projection preserves raw order and duplicate values")
        var draft = region; draft.transcript = nil
        try require(!TextRegionEditing.isComplete(TextRegionEditing.replacing(annotation, regions: [draft])) && TextRegionEditing.isComplete(annotation), "untranscribed drafts cannot be reviewed")
        var blank = region; blank.transcript = "  \n"
        try require(!TextRegionEditing.isComplete(TextRegionEditing.replacing(annotation, regions: [blank])), "whitespace-only transcripts remain incomplete without altering their stored text")
        let old = try JSONDecoder().decode(Annotation.self, from: Data("{\"image_path\":\"old.png\",\"detections\":[],\"reviewed\":true,\"expected_texts\":[\"legacy\"]}".utf8))
        try require(old.textRegions.isEmpty && old.expectedTextSource == "manual" && old.reviewed, "historical annotations decode with manual text and no invented regions")
        let hash = String(repeating: "a", count: 64)
        try require(!TextRegionPredictionCopy.hasSourceIdentity(nil) && !TextRegionPredictionCopy.hasSourceIdentity("old") && TextRegionPredictionCopy.hasSourceIdentity(hash), "legacy previews without image SHA remain visible but cannot be copied")
        var rejected = false
        do { _ = try TextRegionPredictionCopy.verifiedImageHash(preview: hash, current: String(repeating: "b", count: 64)) } catch { rejected = true }
        try require(rejected, "changed source-image bytes reject prediction copy before label mutation")
        let verifiedHash = try TextRegionPredictionCopy.verifiedImageHash(preview: hash, current: hash)
        try require(verifiedHash == hash, "seed image identity comes from the verified preview hash")
        let original = ReadingObservation(text: "XХ", kind: "ocr", box: region.box, polygon: quad, confidence: 0.81)
        let block = FrameInference(blockID: "reader", result: ReadingInference(task: "ocr", readings: [original], identity: ReadingExecutionIdentity(modelID: "apple-vision", adapterID: "apple-vision", provider: "native", identityScope: "system_framework_versioned", identityHash: hash, systemIdentity: [:]), timing: .init(totalMs: 20), warnings: []), inputToFrame: [0.25,0.125,0.5,0.25])
        let copied = try TextRegionPredictionCopy.region(block: block, index: 0, imageSHA256: hash, id: "copied", createdAt: "2026-10-30T12:00:00Z")
        var barcode = block; barcode.result.task = "barcode"
        barcode.result.readings = [ReadingObservation(text: "001234", kind: "barcode", box: region.box, polygon: quad, confidence: nil, symbology: "QR")]
        let copiedBarcode = try TextRegionPredictionCopy.region(block: barcode, index: 0, imageSHA256: hash)
        try require(copiedBarcode.transcript == "001234" && copiedBarcode.seed?.observation.kind == "barcode" && copiedBarcode.seed?.observation.symbology == "QR" && copiedBarcode.seed?.observation.confidence == nil, "barcode copy preserves leading zeros, symbology and unavailable confidence without invented fields")
        try require(abs(copied.polygon[0][0]-0.3) < 1e-9 && abs(copied.polygon[0][1]-0.175) < 1e-9 && copied.seed?.observation.polygon == quad, "prediction copy maps geometry once and preserves original skewed input-space evidence")
        var corrected = copied; corrected.transcript = "XX"; corrected.setPolygon(corner)
        try require(corrected.seed == copied.seed && corrected.box == ReadingGeometry.envelope(corner), "manual correction keeps immutable seed and updates derived envelope")
        let request = ImageAnnotationRequest(baseRevision: 7, annotation: TextRegionEditing.replacing(annotation, regions: [copied]))
        let wire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(request)).object
        let saved = try JSONDecoder().decode(Annotation.self, from: JSONEncoder().encode(wire["annotation"]!))
        try require(wire["base_revision"] == .number(7) && saved.textRegions.first?.seed == copied.seed && saved.expectedTextSource == "regions", "CAS save roundtrip retains seed and source policy")
        let restored = TextRegionEditing.restoring(annotation, from: edited)
        try require(!restored.reviewed && restored.textRegions == annotation.textRegions, "undoing label changes does not restore review automatically")
        let store = DatasetWorkspace(projectID: "checks", client: EngineClient(socketPath: "/tmp/not-contacted-text-region-check.sock"))
        store.annotation = annotation; store.configureLabelMode(reading: true)
        try require(store.labelMode == .textRegions, "reading workspaces default to text authoring")
        store.chooseLabelMode(.objects); store.configureLabelMode(reading: true)
        try require(store.labelMode == .objects, "explicit object mode survives later reading context refresh")
        store.selectedTextRegionID = region.id; store.editTranscript(id: region.id, value: "corrected")
        try require(store.annotation?.textRegions[0].transcript == "corrected" && store.undoStack.count == 1 && store.annotation?.reviewed == false, "store transcript edit is undoable and unreviewed")
        store.undo(); try require(store.annotation?.textRegions[0].transcript == "XХ" && store.annotation?.reviewed == false, "store undo restores transcript without review")
        store.redo(); try require(store.annotation?.textRegions[0].transcript == "corrected", "store redo restores edited transcript")
        store.setReviewed(true); try require(store.annotation?.reviewed == false && store.error != nil, "pending autosave cannot be combined with review approval")
        store.manifest = DatasetManifest(revision: 1, classes: [], images: [DatasetImage(id: "one", imagePath: "/a", width: 100, height: 100, reviewed: false, annotationCount: 0, split: "unassigned", textRegionCount: 1)])
        store.filter = .empty; try require(store.filteredImages.isEmpty, "text-only labelled images do not appear under empty regions and boxes")
        checks += try canvasChecks()
        return checks
    }

    @MainActor private static func canvasChecks() throws -> Int {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("native-text-canvas-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 160, pixelsHigh: 100, bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 480, bitsPerPixel: 24)!
        memset(bitmap.bitmapData!, 255, 48000)
        let image = directory.appendingPathComponent("canvas.png"); try bitmap.representation(using: .png, properties: [:])!.write(to: image)
        let view = AnnotationCanvasView(frame: CGRect(x: 0, y: 0, width: 640, height: 400))
        var drawnText: [Double]?, drawnObject: [Double]?, edited: [TextRegion] = [], editedObjects: [Detection] = []
        func configure(mode: AnnotationLabelMode, tool: AnnotationTool, regions: [TextRegion] = [], selected: String? = nil, objects: [Detection] = []) {
            view.configure(AnnotationCanvas(imagePath: image.path, detections: objects, predictions: [], colors: [:], selectedIndex: objects.isEmpty ? nil : 0, tool: tool, zoom: 1, fitToken: 0,
                onSelect: { _ in }, onCreate: { drawnObject = $0 }, onEdit: { editedObjects = $0 }, onCommand: { _ in }, onZoom: { _ in },
                labelMode: mode, textRegions: regions, selectedTextRegionID: selected, onTextSelect: { _ in }, onTextCreate: { drawnText = $0 }, onTextEdit: { edited = $0 }))
        }
        func drag(_ start: CGPoint, _ end: CGPoint) {
            func event(_ type: NSEvent.EventType, _ location: CGPoint) -> NSEvent {
                NSEvent.mouseEvent(with: type, location: view.convert(location, to: nil), modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil, eventNumber: 0, clickCount: 1, pressure: 1)!
            }
            view.mouseDown(with: event(.leftMouseDown, start)); view.mouseDragged(with: event(.leftMouseDragged, end)); view.mouseUp(with: event(.leftMouseUp, end))
        }
        configure(mode: .textRegions, tool: .box)
        drag(CGPoint(x: 64, y: 80), CGPoint(x: 320, y: 200))
        guard let box = drawnText, abs(box[0]-0.1) < 1e-8, abs(box[3]-0.5) < 1e-8, drawnObject == nil else { throw EngineError.protocolError("Text canvas draw crossed into object labels") }
        let region = TextRegion(id: "canvas", polygon: TextRegionGeometry.rectangle(box), box: box, transcript: "text")
        configure(mode: .textRegions, tool: .select, regions: [region], selected: region.id)
        drag(CGPoint(x: 180, y: 140), CGPoint(x: 244, y: 180))
        guard edited.count == 1, abs(edited[0].polygon[0][0]-0.2) < 1e-8, abs(edited[0].polygon[0][1]-0.3) < 1e-8 else { throw EngineError.protocolError("Text canvas move did not persist normalized geometry") }
        let moved = edited[0]
        configure(mode: .textRegions, tool: .select, regions: [moved], selected: moved.id)
        let origin = TextRegionGeometry.screenPoint(moved.polygon[0], rect: view.bounds)
        drag(origin, CGPoint(x: origin.x+12, y: origin.y+8))
        guard edited[0].polygon[0] != moved.polygon[0], edited[0].polygon[1] == moved.polygon[1], TextRegionGeometry.valid(edited[0].polygon) else { throw EngineError.protocolError("Text canvas corner editing failed") }
        drawnText = nil; configure(mode: .objects, tool: .box)
        drag(CGPoint(x: 64, y: 80), CGPoint(x: 320, y: 200))
        guard drawnObject == box, drawnText == nil else { throw EngineError.protocolError("Text mode regressed object box drawing") }
        configure(mode: .objects, tool: .select, objects: [Detection(label: "object", confidence: 1, box: box)])
        drag(CGPoint(x: 180, y: 140), CGPoint(x: 244, y: 180))
        guard editedObjects.count == 1, abs(editedObjects[0].box[0]-0.2) < 1e-8 else { throw EngineError.protocolError("Text mode regressed object box movement") }
        let movedObject = editedObjects[0]
        configure(mode: .objects, tool: .select, objects: [movedObject])
        let objectCorner = CGPoint(x: movedObject.box[2]*640, y: movedObject.box[3]*400)
        drag(objectCorner, CGPoint(x: objectCorner.x+20, y: objectCorner.y+16))
        guard editedObjects[0].box[2] > movedObject.box[2], editedObjects[0].box[0] == movedObject.box[0] else { throw EngineError.protocolError("Text mode regressed object box resizing") }
        return 6
    }
}
