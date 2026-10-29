import Foundation
import CoreGraphics

enum ReadingEvidenceChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw EngineError.protocolError("Reading evidence check failed: " + message) }; checks += 1
        }
        let converted = ReadingGeometry.fromVision([CGPoint(x: 0.125, y: 0.75), CGPoint(x: 0.75, y: 0.75), CGPoint(x: 0.75, y: 0.5), CGPoint(x: 0.125, y: 0.5)])
        try require(converted?.box == [0.125, 0.25, 0.75, 0.5], "Vision lower-left geometry converts to top-left exactly once")
        try require(converted?.polygon.first == [0.125, 0.25] && converted?.polygon.last == [0.125, 0.5], "quad order preserves corner identity")
        try require(ReadingGeometry.fromVision([CGPoint(x: -0.1, y: 0.5), CGPoint(x: 1, y: 0.5), CGPoint(x: 1, y: 1)]) == nil, "out-of-frame geometry is omitted rather than clamped")
        try require(ReadingGeometry.envelope([[0,0],[0.5,0.5],[1,1]]) == nil && ReadingGeometry.envelope([[0,0],[.nan,1],[1,0]]) == nil, "degenerate and nonfinite geometry is rejected")
        let reading = ReadingObservation(text: "ABC-990", kind: "ocr", box: converted?.box, polygon: converted?.polygon, confidence: 0.75, symbology: nil)
        let mapped = ReadingGeometry.mapped(reading, transform: [0.25, 0.125, 0.5, 0.25])
        try require(mapped.box == [0.3125,0.1875,0.625,0.25] && mapped.text == reading.text, "crop and resize affine transform is applied once without changing text")
        try require(mapped.box == ReadingGeometry.envelope(mapped.polygon!), "display box remains the quad envelope")
        let missing = ReadingObservation(text: "payload", kind: "barcode", confidence: nil, symbology: "QR")
        try require(ReadingGeometry.mapped(missing, transform: [0,0,1,1]).box == nil, "missing geometry never becomes a full-frame region")
        try require(ReadingGeometry.mapped(reading, transform: [0,0,-1,1]).box == nil, "invalid transforms cannot render a misleading overlay")
        let encodedMissing = try JSONSerialization.jsonObject(with: JSONEncoder().encode(missing)) as! [String: Any]
        try require(encodedMissing["confidence"] is NSNull && encodedMissing["box"] is NSNull && encodedMissing["polygon"] is NSNull, "protocol explicitly preserves unavailable confidence and geometry as null")
        let legacy = NativeReadings(texts: ["X", "X"], barcodes: [])
        let legacyWire = try JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as! [String: Any]
        try require(Set(legacyWire.keys) == Set(["texts", "barcodes"]), "legacy CLI output remains exactly the two legacy fields")
        let rich = NativeReadingsV2(inputSize: [1000,300], texts: ["ABC-990"], barcodes: ["payload"], readings: [reading,missing], warnings: [])
        let richWire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(rich)).object
        try require(richWire["schema_version"] == .number(2) && richWire["coordinate_space"] == .string("normalized_top_left") && richWire["request_policy"] == .string("apple-vision-en-us-v2"), "rich output protocol and recognition policy are explicit and separate")
        try require(VisionBridge.protocolVersion(arguments: ["app","--analyze-image","file"]) == 1 && VisionBridge.protocolVersion(arguments: ["app","--analyze-image","file","--protocol","2"]) == 2, "legacy and rich commands select explicit versions")
        try require(VisionBridge.protocolVersion(arguments: ["app","--analyze-image","file","--protocol","3"]) == nil, "unknown protocol cannot silently fall back")
        let wire = Data("""
        {"image_path":"/one/frame.png","detections":[],"counts":{},"texts":["X","X"],"events":[],"elapsed_ms":10,"inferences":[{"block_id":"reader","input_to_frame":[0.25,0.125,0.5,0.25],"result":{"task":"ocr","readings":[{"text":"X","kind":"ocr","box":[0.125,0.25,0.75,0.5],"polygon":null,"confidence":0.75,"symbology":null},{"text":"X","kind":"ocr","box":null,"polygon":null,"confidence":null,"symbology":null}],"identity":{"model_id":"actual-reader","adapter_id":"actual-adapter","provider":"native","identity_scope":"system_framework_versioned","identity_hash":"identity","system_identity":{"policy":"test"}},"timing":{"total_ms":9},"warnings":[]}}]}
        """.utf8)
        let frame = try JSONDecoder().decode(FrameResult.self, from: wire)
        let blocks = ReadingPresentation.blocks(frame), rows = ReadingPresentation.readings(blocks)
        try require(rows.count == 2 && rows[0].id != rows[1].id, "duplicate strings remain distinct observations")
        try require(rows[0].observation.box == mapped.box && rows[1].observation.box == nil, "wire input-space geometry maps once while missing geometry stays missing")
        try require(blocks[0].result.identity.modelID == "actual-reader" && blocks[0].result.timing.totalMs == 9, "reader name and timing derive from execution evidence")
        var oldWire = try JSONDecoder().decode(JSONValue.self, from: wire).object; oldWire.removeValue(forKey: "inferences")
        let old = try JSONDecoder().decode(FrameResult.self, from: JSONEncoder().encode(oldWire))
        try require(old.inferences == nil && old.texts == ["X","X"], "historical frames remain readable without fabricated regions")
        try require(ReadingPresentation.exactFrame([frame], imagePath: "/two/frame.png") == nil, "same filename in another directory cannot borrow reading evidence")
        try require(ReadingPresentation.codePoints("XХ") == "U+0058 U+0425", "visually similar Latin and Cyrillic characters are not normalized away")
        let annotation = Annotation(imagePath: "frame", detections: [], reviewed: true, expectedTexts: ["old"], proposal: .object(["source": .string("model_hypothesis")]))
        let corrected = ExpectedTextEditing.update(annotation, values: ["XХ"])
        try require(!corrected.reviewed && corrected.proposal == annotation.proposal && corrected.detections == annotation.detections, "text correction clears review while preserving provenance and object labels")
        let mixedPipeline = Pipeline(name: "Read and inspect", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "reader", type: "ocr"), PipelineBlock(id: "inspection", type: "vlm_judge")])
        var mixed = frame; mixed.texts = ["X", "damaged"]
        let mixedOutput = ReadingPresentation.workflowText(mixed, pipeline: mixedPipeline)
        try require(mixedOutput?.values == ["X", "damaged"] && mixedOutput?.readerEvidenceUnavailable == false && ReadingPresentation.blocks(mixed).count == 1, "rich OCR evidence cannot hide a different block's workflow text output")
        let judgementPipeline = Pipeline(name: "Inspect", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "inspection", type: "vlm_judge")])
        let judgementOutput = ReadingPresentation.workflowText(old, pipeline: judgementPipeline)
        try require(judgementOutput?.values == old.texts && judgementOutput?.readerEvidenceUnavailable == false, "current judgement-only output is not misclassified as missing reader evidence")
        try require(ReadingPresentation.workflowText(old, pipeline: mixedPipeline)?.readerEvidenceUnavailable == true, "known reading workflow without rich observations reports unavailable regions without inventing geometry")
        var empty = old; empty.texts = []
        try require(ReadingPresentation.workflowText(empty, pipeline: nil) == nil && ReadingPresentation.workflowText(empty, pipeline: judgementPipeline)?.values == [], "empty text-capable workflows remain explicit while nontext workflows gain no invented text state")
        return checks
    }
}
