import Foundation

struct TextRegionSeed: Codable, Equatable {
    var source = "model_reading"
    var modelID: String
    var adapterID: String
    var identityHash: String
    var blockID: String
    var observationIndex: Int
    var observation: ReadingObservation
    var inputToFrame: [Double]
    var imageSHA256: String
    var createdAt: String
    enum CodingKeys: String, CodingKey {
        case source, modelID = "model_id", adapterID = "adapter_id", identityHash = "identity_hash", blockID = "block_id"
        case observationIndex = "observation_index", observation, inputToFrame = "input_to_frame", imageSHA256 = "image_sha256", createdAt = "created_at"
    }
}

struct TextRegion: Codable, Identifiable, Equatable {
    var id: String
    var polygon: [[Double]]
    var box: [Double]
    var transcript: String?
    var seed: TextRegionSeed?
    mutating func setPolygon(_ polygon: [[Double]]) {
        guard TextRegionGeometry.valid(polygon), let box = ReadingGeometry.envelope(polygon) else { return }
        self.polygon = polygon; self.box = box
    }
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.id == rhs.id && lhs.polygon == rhs.polygon && lhs.box == rhs.box && lhs.seed == rhs.seed &&
            lhs.transcript.map { Data($0.utf8) } == rhs.transcript.map { Data($0.utf8) }
    }
    enum CodingKeys: String, CodingKey { case id, polygon, box, transcript, seed }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id); try c.encode(polygon, forKey: .polygon); try c.encode(box, forKey: .box)
        try c.encode(transcript, forKey: .transcript); try c.encode(seed, forKey: .seed)
    }
}

extension Annotation {
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        imagePath = try c.decode(String.self, forKey: .imagePath)
        detections = try c.decode([Detection].self, forKey: .detections)
        reviewed = try c.decode(Bool.self, forKey: .reviewed)
        expectedTexts = try c.decode([String].self, forKey: .expectedTexts)
        proposal = try c.decodeIfPresent(JSONValue.self, forKey: .proposal)
        textRegions = try c.decodeIfPresent([TextRegion].self, forKey: .textRegions) ?? []
        expectedTextSource = try c.decodeIfPresent(String.self, forKey: .expectedTextSource) ?? "manual"
    }
}
