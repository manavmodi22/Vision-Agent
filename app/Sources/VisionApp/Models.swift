import Foundation

enum JSONValue: Codable, Equatable {
    case string(String), number(Double), bool(Bool), array([JSONValue]), object([String: JSONValue]), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .bool(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    var string: String? { if case .string(let v) = self { return v }; return nil }
    var object: [String: JSONValue] { if case .object(let v) = self { return v }; return [:] }
    var display: String {
        switch self { case .string(let s): return s; case .number(let n): return String(n)
        case .bool(let b): return b ? "Yes" : "No"; default: return "" }
    }
}

struct Pipeline: Codable, Identifiable, Equatable {
    var name: String
    var specVersion: String
    var inputs: [String: JSONValue]
    var blocks: [PipelineBlock]
    var evaluation: JSONValue?
    var id: String { name }
    enum CodingKeys: String, CodingKey { case name, specVersion = "spec_version", inputs, blocks, evaluation = "eval" }
}
struct PipelineBlock: Codable, Identifiable, Equatable {
    var id: String
    var type: String
    var params: [String: JSONValue]?
    var connections: [String: JSONValue]?
    enum CodingKeys: String, CodingKey { case id, type, params, connections = "in" }
}
struct Detection: Codable, Equatable, Identifiable {
    var label: String
    var confidence: Double
    var box: [Double]
    var zone: String?
    var id: String { "\(label)-\(box)" }
}
struct FrameResult: Codable, Identifiable {
    var imagePath: String
    var detections: [Detection]
    var counts: [String: Int]
    var texts: [String]
    var events: [JSONValue]
    var elapsedMs: Double
    var inferences: [FrameInference]? = nil
    var sourceImageSHA256: String? = nil
    var id: String { imagePath }
    enum CodingKeys: String, CodingKey { case imagePath = "image_path", detections, counts, texts, events, elapsedMs = "elapsed_ms", inferences, sourceImageSHA256 = "source_image_sha256" }
}
struct RunResult: Codable {
    var frames: [FrameResult]
    var elapsedS: Double
    var warnings: [String]
    enum CodingKeys: String, CodingKey { case frames, elapsedS = "elapsed_s", warnings }
}
struct Evaluation: Codable, Identifiable {
    var precision: Double
    var recall: Double
    var countMae: Double
    var passed: Bool
    var metric: String
    var target: Double
    var sampleCount: Int
    var failures: [JSONValue]
    var specHash: String
    var datasetHash: String
    var textAccuracy: Double?
    var warnings: [String]?
    var characterErrorRate: Double?
    var wordErrorRate: Double?
    var textNormalization: String?
    var textErrorCounts: [String: Int?]?
    var protocolID: String?
    var protocolHash: String?
    var evidenceScope: String?
    var promotionEligible: Bool?
    var evidenceReasons: [String]?
    var id: String { specHash }
    enum CodingKeys: String, CodingKey {
        case precision, recall, countMae = "count_mae", passed, metric, target
        case sampleCount = "sample_count", failures, specHash = "spec_hash", datasetHash = "dataset_hash"
        case textAccuracy = "text_accuracy", warnings
        case characterErrorRate = "character_error_rate", wordErrorRate = "word_error_rate"
        case textNormalization = "text_normalization", textErrorCounts = "text_error_counts"
        case protocolID = "protocol_id", protocolHash = "protocol_hash", evidenceScope = "evidence_scope"
        case promotionEligible = "promotion_eligible", evidenceReasons = "evidence_reasons"
    }
}
struct ChatMessage: Codable, Identifiable {
    var role: String
    var content: String
    var id: String { role + content }
}
struct Project: Codable, Identifiable {
    var id: String
    var name: String
    var useCase: String
    var status: String
    var createdAt: String
    var updatedAt: String
    var media: [String]
    var brief: String?
    var candidates: [Pipeline]
    var evaluations: [Evaluation]
    var messages: [ChatMessage]
    var synthetic: Bool
    var fixture: Bool?
    var dataOrigin: String?
    var deploymentId: String?
    var approvalScope: String?
    var trialLimits: [String: Int]?
    enum CodingKeys: String, CodingKey {
        case id, name, useCase = "use_case", status, createdAt = "created_at", updatedAt = "updated_at"
        case media, brief, candidates, evaluations, messages, synthetic, fixture, dataOrigin = "data_origin", deploymentId = "deployment_id"
        case approvalScope = "approval_scope", trialLimits = "trial_limits"
    }
}
struct Annotation: Codable, Identifiable, Equatable {
    var imagePath: String
    var detections: [Detection]
    var reviewed: Bool
    var expectedTexts: [String]
    var proposal: JSONValue?
    var textRegions: [TextRegion] = []
    var expectedTextSource = "manual"
    var id: String { imagePath }
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.imagePath == rhs.imagePath && lhs.detections == rhs.detections && lhs.reviewed == rhs.reviewed &&
            lhs.expectedTexts.map { Data($0.utf8) } == rhs.expectedTexts.map { Data($0.utf8) } &&
            lhs.proposal == rhs.proposal && lhs.textRegions == rhs.textRegions && lhs.expectedTextSource == rhs.expectedTextSource
    }
    enum CodingKeys: String, CodingKey { case imagePath = "image_path", detections, reviewed, expectedTexts = "expected_texts", proposal, textRegions = "text_regions", expectedTextSource = "expected_text_source" }
}
struct EvalDataset: Codable {
    var id: String
    var annotations: [Annotation]
}
struct EventRecord: Codable, Identifiable {
    var id: String
    var createdAt: String
    var imagePath: String?
    var cropPath: String?
    var label: String
    var confidence: Double?
    var counts: [String: Int]?
    var payload: JSONValue?
    enum CodingKeys: String, CodingKey { case id, createdAt = "created_at", imagePath = "image_path", cropPath = "crop_path", label, confidence, counts, payload }
}
struct ReviewEntry: Codable, Identifiable {
    var id: String
    var imagePath: String
    var reason: String
    var status: String
    enum CodingKeys: String, CodingKey { case id, imagePath = "image_path", reason, status }
}
struct AppSettings: Codable {
    var modelUrl = "http://localhost:1234/v1"
    var plannerModel = ""
    var vlmModel = ""
    var vlmUrl = "http://127.0.0.1:1235/v1"
    var allowAgpl = false
    enum CodingKeys: String, CodingKey { case modelUrl = "model_url", plannerModel = "planner_model", vlmModel = "vlm_model", vlmUrl = "vlm_url", allowAgpl = "allow_agpl" }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelUrl = try c.decodeIfPresent(String.self, forKey: .modelUrl) ?? "http://localhost:1234/v1"
        plannerModel = try c.decodeIfPresent(String.self, forKey: .plannerModel) ?? ""
        vlmModel = try c.decodeIfPresent(String.self, forKey: .vlmModel) ?? ""
        vlmUrl = try c.decodeIfPresent(String.self, forKey: .vlmUrl) ?? "http://127.0.0.1:1235/v1"
        allowAgpl = try c.decodeIfPresent(Bool.self, forKey: .allowAgpl) ?? false
    }
}
struct Zone: Codable, Identifiable {
    var id: String
    var polygon: [[Double]]
}
struct PlanResponse: Codable {
    var message: String
    var questions: [String]
    var candidates: [Pipeline]
    var project: Project
}
struct AskResponse: Codable { var answer: String; var evidence: [EventRecord] }

struct ZonesResponse: Codable { var zones: [Zone]; var confirmed: Bool?; var origin: String? }

struct TrainingJob: Codable {
    var id: String
    var status: String
    var message: String?
    var progress: Double?
    var result: JSONValue?
    var error: String?
}
