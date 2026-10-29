import Foundation

struct EvaluationPolicy: Codable, Equatable {
    var intendedUse: String
    var independentGroupBasis: String
    var requiredAcceptanceGroups: [String]
    var coverageRationale: String
    enum CodingKeys: String, CodingKey {
        case intendedUse = "intended_use", independentGroupBasis = "independent_group_basis"
        case requiredAcceptanceGroups = "required_acceptance_groups", coverageRationale = "coverage_rationale"
    }
}
struct EvidenceImage: Decodable, Identifiable, Equatable {
    let imagePath: String
    let sourceAssetID: String?
    let sourceSHA256: String?
    let frameIndex: Int?
    let timestampS: Double?
    var sceneGroup: String?
    var split: String
    var dataOrigin: String
    let groupProvenance: String
    let exposureReasons: [String]
    var id: String { imagePath }
    var filename: String { URL(fileURLWithPath: imagePath).lastPathComponent }
    enum CodingKeys: String, CodingKey {
        case imagePath = "image_path", sourceAssetID = "source_asset_id", sourceSHA256 = "source_sha256"
        case frameIndex = "frame_index", timestampS = "timestamp_s", sceneGroup = "scene_group"
        case split, dataOrigin = "data_origin", groupProvenance = "group_provenance", exposureReasons = "exposure_reasons"
    }
}
struct EvaluationConfiguration: Decodable, Equatable {
    let revision: String
    var images: [EvidenceImage]
    var policy: EvaluationPolicy
}
struct EvaluationReadiness: Decodable {
    let candidateIndex: Int
    let acceptanceAvailable: Bool
    let acceptanceReplayAvailable: Bool?
    let acceptanceBlockers: [String]
    let currentAcceptance: Evaluation?
    enum CodingKeys: String, CodingKey {
        case candidateIndex = "candidate_index", acceptanceAvailable = "acceptance_available"
        case acceptanceReplayAvailable = "acceptance_replay_available"
        case acceptanceBlockers = "acceptance_blockers", currentAcceptance = "current_acceptance"
    }
}
struct EvidenceAssignment: Encodable {
    let imagePath: String
    let sceneGroup: String?
    let split: String
    let dataOrigin: String
    init(_ image: EvidenceImage) {
        imagePath = image.imagePath; sceneGroup = image.sceneGroup; split = image.split; dataOrigin = image.dataOrigin
    }
    enum CodingKeys: String, CodingKey { case imagePath = "image_path", sceneGroup = "scene_group", split, dataOrigin = "data_origin" }
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(imagePath, forKey: .imagePath); try container.encode(sceneGroup, forKey: .sceneGroup)
        try container.encode(split, forKey: .split); try container.encode(dataOrigin, forKey: .dataOrigin)
    }
}
struct EvaluationConfigurationRequest: Encodable {
    let expectedRevision: String
    let assignments: [EvidenceAssignment]
    let policy: EvaluationPolicy
    init(_ configuration: EvaluationConfiguration) {
        expectedRevision = configuration.revision; assignments = configuration.images.map(EvidenceAssignment.init); policy = configuration.policy
    }
    enum CodingKeys: String, CodingKey { case expectedRevision = "expected_revision", assignments, policy }
}

enum EvaluationEvidencePresentation {
    static func imagePath(_ path: String, projectMedia: [String]) -> String? {
        if path.hasPrefix("/") { return path }
        let matches = projectMedia.filter { $0.hasPrefix("/") && $0.hasSuffix("/" + path) }
        return matches.count == 1 ? matches[0] : nil
    }
    static func scope(_ evaluation: Evaluation) -> String {
        switch evaluation.evidenceScope {
        case "sample": return "Sample evidence"
        case "validation": return "Validation comparison"
        case "acceptance": return "Independent acceptance"
        default: return "Historical result · evidence unknown"
        }
    }
    static func hasProtocol(_ evaluation: Evaluation?) -> Bool {
        guard let evaluation else { return false }
        return evaluation.protocolID?.isEmpty == false && evaluation.protocolHash?.isEmpty == false && ["sample", "validation", "acceptance"].contains(evaluation.evidenceScope ?? "")
    }
    static func canPromote(_ evaluation: Evaluation?) -> Bool {
        hasProtocol(evaluation) && evaluation?.evidenceScope == "acceptance" && evaluation?.promotionEligible == true && evaluation?.passed == true
    }
    static func qualityTitle(_ evaluation: Evaluation) -> String {
        if !hasProtocol(evaluation) { return "Quality evidence unknown · re-evaluate" }
        if canPromote(evaluation) { return "Eligible for quality promotion" }
        return "Quality promotion not established"
    }
    static func reasons(_ evaluation: Evaluation) -> [String] {
        if !hasProtocol(evaluation) { return ["This saved result has no current evaluation protocol. Run a fresh evaluation before requesting a new approval."] }
        return evaluation.evidenceReasons ?? []
    }
}
