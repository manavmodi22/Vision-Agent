import Foundation
import CoreGraphics

struct ReadingObservation: Codable, Equatable {
    var text: String
    var kind: String
    var box: [Double]?
    var polygon: [[Double]]?
    var confidence: Double?
    var symbology: String?
    enum CodingKeys: String, CodingKey { case text, kind, box, polygon, confidence, symbology }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(text, forKey: .text); try c.encode(kind, forKey: .kind)
        try c.encode(box, forKey: .box); try c.encode(polygon, forKey: .polygon)
        try c.encode(confidence, forKey: .confidence); try c.encode(symbology, forKey: .symbology)
    }
}

struct ReadingExecutionIdentity: Codable {
    var modelID: String
    var adapterID: String
    var provider: String
    var identityScope: String
    var identityHash: String
    var systemIdentity: [String: String]
    enum CodingKeys: String, CodingKey {
        case modelID = "model_id", adapterID = "adapter_id", provider, identityScope = "identity_scope"
        case identityHash = "identity_hash", systemIdentity = "system_identity"
    }
}
struct ReadingInference: Codable {
    var task: String
    var readings: [ReadingObservation]
    var identity: ReadingExecutionIdentity
    var timing: Timing
    var warnings: [String]
    struct Timing: Codable { var totalMs: Double; enum CodingKeys: String, CodingKey { case totalMs = "total_ms" } }
}
struct FrameInference: Codable {
    var blockID: String
    var result: ReadingInference
    var inputToFrame: [Double]
    enum CodingKeys: String, CodingKey { case blockID = "block_id", result, inputToFrame = "input_to_frame" }
}

struct DisplayReading: Identifiable {
    var id: String
    var blockID: String
    var index: Int
    var observation: ReadingObservation
}

struct WorkflowTextOutput {
    let values: [String]
    let readerEvidenceUnavailable: Bool
}

enum ReadingGeometry {
    static func envelope(_ polygon: [[Double]]) -> [Double]? {
        guard polygon.count >= 3, polygon.allSatisfy({ $0.count == 2 && $0.allSatisfy { $0.isFinite && (0...1).contains($0) } }) else { return nil }
        let area = polygon.indices.reduce(0.0) { sum, i in
            let p = polygon[i], next = polygon[(i+1) % polygon.count]
            return sum + p[0]*next[1] - next[0]*p[1]
        }
        guard abs(area) >= 1e-8 else { return nil }
        return [polygon.map { $0[0] }.min()!, polygon.map { $0[1] }.min()!, polygon.map { $0[0] }.max()!, polygon.map { $0[1] }.max()!]
    }
    static func fromVision(_ points: [CGPoint]) -> (box: [Double], polygon: [[Double]])? {
        let polygon = points.map { [Double($0.x), 1-Double($0.y)] }
        guard let box = envelope(polygon) else { return nil }
        return (box, polygon)
    }
    static func mapped(_ reading: ReadingObservation, transform: [Double]) -> ReadingObservation {
        var result = reading; result.box = nil; result.polygon = nil
        guard transform.count == 4, transform.allSatisfy(\.isFinite), transform[0] >= 0, transform[1] >= 0,
              transform[2] > 0, transform[3] > 0, transform[0]+transform[2] <= 1+1e-8, transform[1]+transform[3] <= 1+1e-8 else { return result }
        let points: [[Double]]
        if let polygon = reading.polygon { points = polygon }
        else if let b = reading.box, b.count == 4, b[0] < b[2], b[1] < b[3] { points = [[b[0],b[1]], [b[2],b[1]], [b[2],b[3]], [b[0],b[3]]] }
        else { return result }
        guard envelope(points) != nil else { return result }
        let mapped = points.map { [transform[0]+$0[0]*transform[2], transform[1]+$0[1]*transform[3]] }
        guard let box = envelope(mapped) else { return result }
        result.box = box; result.polygon = mapped; return result
    }
}

enum ReadingPresentation {
    static func workflowText(_ frame: FrameResult, pipeline: Pipeline?) -> WorkflowTextOutput? {
        let isReader = EvaluationPresentation.isReading(pipeline)
        let hasJudgement = pipeline?.blocks.contains { $0.type == "vlm_judge" } == true
        guard !frame.texts.isEmpty || isReader || hasJudgement else { return nil }
        return WorkflowTextOutput(values: frame.texts, readerEvidenceUnavailable: isReader && blocks(frame).isEmpty)
    }
    static func blocks(_ frame: FrameResult?) -> [FrameInference] {
        (frame?.inferences ?? []).filter { ["ocr", "barcode"].contains($0.result.task) }
    }
    static func readings(_ blocks: [FrameInference]) -> [DisplayReading] {
        blocks.flatMap { block in
            block.result.readings.enumerated().map { index, reading in
                DisplayReading(id: "\(block.blockID):\(index)", blockID: block.blockID, index: index,
                               observation: ReadingGeometry.mapped(reading, transform: block.inputToFrame))
            }
        }
    }
    static func codePoints(_ text: String) -> String { text.unicodeScalars.map { String(format: "U+%04X", $0.value) }.joined(separator: " ") }
    static func exactFrame(_ frames: [FrameResult], imagePath: String) -> FrameResult? {
        let canonical = URL(fileURLWithPath: imagePath).standardizedFileURL.resolvingSymlinksInPath().path
        return frames.first { URL(fileURLWithPath: $0.imagePath).standardizedFileURL.resolvingSymlinksInPath().path == canonical }
    }
}
