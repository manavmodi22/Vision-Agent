import Foundation
import CoreGraphics

enum AnnotationContractChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw EngineError.protocolError("Annotation check failed: " + message) }
            checks += 1
        }
        let box = [0.2, 0.1, 0.5, 0.4]
        let moved = AnnotationGeometry.move(box, dx: 0.9, dy: -0.8)
        try require(abs(moved[0]-0.7) < 1e-9 && moved[1] == 0 && moved[2] == 1, "moving clamps without changing box size")
        let resized = AnnotationGeometry.resize(box, handle: .topLeft, dx: 1, dy: 1)
        try require(abs(resized[0]-(box[2]-0.001)) < 1e-9 && resized[0] < resized[2] && resized[1] < resized[3], "resize cannot invert a box")
        let rect = AnnotationGeometry.imageRect(image: CGSize(width: 1000, height: 500), viewport: CGSize(width: 800, height: 600), zoom: 2, pan: CGPoint(x: 30, y: -20))
        let screenBox = AnnotationGeometry.boxRect(box, image: rect)
        let point = AnnotationGeometry.point(screenBox.origin, image: rect)
        try require(abs(point.x-box[0]) < 1e-9 && abs(point.y-box[1]) < 1e-9, "zoom and pan preserve normalized coordinates")
        try require(AnnotationGeometry.handle(at: CGPoint(x: screenBox.maxX, y: screenBox.maxY), box: screenBox) == .bottomRight, "resize handle hit testing")
        let annotation = try JSONDecoder().decode(Annotation.self, from: Data("""
        {"image_path":"media/a.jpg","detections":[{"label":"person","confidence":0.7,"box":[0.2,0.1,0.5,0.4],"zone":null}],"reviewed":false,"expected_texts":[],"proposal":{"status":"model_hypothesis","model":"local-detector"}}
        """.utf8))
        let encoded = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(ImageAnnotationRequest(baseRevision: 12, annotation: annotation)))
        try require(encoded.object["base_revision"] == .number(12), "autosave uses revision wire key")
        try require(encoded.object["annotation"]?.object["proposal"]?.object["status"] == .string("model_hypothesis"), "proposal provenance is preserved")
        let oldSettings = try JSONDecoder().decode(AppSettings.self, from: Data("{\"model_url\":\"http://localhost:1234/v1\",\"planner_model\":\"planner\",\"vlm_model\":\"vision\",\"allow_agpl\":false}".utf8))
        try require(oldSettings.vlmUrl == "http://127.0.0.1:1235/v1", "old settings use the VLM endpoint default")
        let settingsJSON = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(oldSettings))
        try require(settingsJSON.object["vlm_url"] == .string("http://127.0.0.1:1235/v1"), "settings save preserves separate VLM endpoint")
        try require(AppSettings().investigationTransport == "structured_json" && oldSettings.investigationTransport == "structured_json", "new and historical settings default to the existing JSON schema transport")
        try require(settingsJSON.object["investigation_transport"] == .string("structured_json") && settingsJSON.object["investigationTransport"] == nil, "settings encode the exact transport wire key")
        var functionSettings = try JSONDecoder().decode(AppSettings.self, from: Data("{\"model_url\":\"http://localhost:1234/v1\",\"investigation_transport\":\"decision_function\"}".utf8))
        try require(functionSettings.investigationTransport == "decision_function", "function-call transport is retained when settings load")
        functionSettings.plannerModel = "changed-planner"
        let functionJSON = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(functionSettings))
        try require(functionJSON.object["investigation_transport"] == .string("decision_function") && functionJSON.object["planner_model"] == .string("changed-planner"), "an unrelated settings edit does not reset the investigation transport")
        let futureSettings = try JSONDecoder().decode(AppSettings.self, from: Data("{\"investigation_transport\":\"future_format\"}".utf8))
        let futureJSON = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(futureSettings))
        try require(futureJSON.object["investigation_transport"] == .string("future_format"), "an unfamiliar server format is preserved rather than silently replaced on save")
        let frame = BlockDefinition(type: "frame_sample", description: "Frames", params: .object([:]), inputs: ["frames": "frames"], outputs: ["frame": "image"])
        let detect = BlockDefinition(type: "detect", description: "Detect", params: .object([:]), inputs: ["image": "image"], outputs: ["dets": "detections"])
        let count = BlockDefinition(type: "count_per_zone", description: "Count", params: .object([:]), inputs: ["dets": "detections"], outputs: ["counts": "counts"])
        let pipeline = Pipeline(name: "Editable", specVersion: "0.1", inputs: [:], blocks: [
            PipelineBlock(id: "sample", type: "frame_sample", params: [:], connections: [:]),
            PipelineBlock(id: "detect", type: "detect", params: [:], connections: [:]),
            PipelineBlock(id: "count", type: "count_per_zone", params: [:], connections: [:])])
        let catalog = [frame, detect, count]
        try require(BlockGraphEditing.compatibleSources(pipeline: pipeline, blockIndex: 1, input: "image", catalog: catalog).map(\.reference) == ["$sample.frame"], "image input receives only upstream image outputs")
        try require(BlockGraphEditing.compatibleSources(pipeline: pipeline, blockIndex: 2, input: "dets", catalog: catalog).map(\.reference) == ["$detect.dets"], "detection ports exclude image outputs")
        try require(BlockGraphEditing.compatibleSources(pipeline: pipeline, blockIndex: 0, input: "frames", catalog: catalog).map(\.reference) == ["$inputs.source"], "source port is frames only")
        try require(BlockGraphEditing.uniqueID(type: "detect", blocks: pipeline.blocks) == "detect_2", "new blocks use a unique identifier")
        var edited = pipeline; edited.name = "Edited workflow"
        let candidateRequest = CandidateUpdateRequest(spec: edited, baseSpec: pipeline)
        let candidateJSON = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(candidateRequest))
        try require(candidateJSON.object["base_spec"]?.object["name"] == .string("Editable"), "workflow save carries its original baseline")
        try require(candidateJSON.object["spec"]?.object["name"] == .string("Edited workflow"), "edited workflow and baseline remain separate")
        let storedZone = Zone(id: "A", polygon: [[0, 0], [1, 0], [1, 1], [0, 1]])
        try require(PreviewPresentation.zones(for: pipeline, savedZones: [storedZone]).isEmpty, "workflows without zone_filter show no zone overlay")
        var zonePipeline = pipeline
        zonePipeline.blocks.append(PipelineBlock(id: "zones", type: "zone_filter", params: [:], connections: [:]))
        try require(PreviewPresentation.zones(for: zonePipeline, savedZones: [storedZone]).map(\.id) == ["A"], "default zone_filter uses saved lane geometry")
        zonePipeline.blocks[3].params = ["zones": .array([.object(["id": .string("Inline"), "polygon": .array([.array([.number(0), .number(0)]), .array([.number(1), .number(0)]), .array([.number(1), .number(1)])])])])]
        try require(PreviewPresentation.zones(for: zonePipeline, savedZones: [storedZone]).map(\.id) == ["Inline"], "inline zone geometry replaces unrelated saved lanes")
        zonePipeline.blocks[3].params = ["zones": .string("zones/other.json")]
        try require(PreviewPresentation.zones(for: zonePipeline, savedZones: [storedZone]).isEmpty, "unloaded zone files never borrow unrelated lane overlays")
        return checks
    }
}
