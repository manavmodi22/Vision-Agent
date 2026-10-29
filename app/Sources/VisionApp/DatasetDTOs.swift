import Foundation

struct DatasetClass: Codable, Identifiable, Equatable {
    var id: String
    var name: String
    var color: String
}
struct DatasetImage: Codable, Identifiable, Equatable {
    var id: String
    var imagePath: String
    var width: Int
    var height: Int
    var reviewed: Bool
    var annotationCount: Int
    var split: String
    var filename: String { URL(fileURLWithPath: imagePath).lastPathComponent }
    enum CodingKeys: String, CodingKey { case id, width, height, reviewed, split, imagePath = "image_path", annotationCount = "annotation_count" }
}
struct DatasetManifest: Codable {
    var revision: Int
    var classes: [DatasetClass]
    var images: [DatasetImage]
}
struct ImageAnnotationResponse: Codable {
    var revision: Int
    var annotation: Annotation
}
struct ImageAnnotationRequest: Codable {
    var baseRevision: Int
    var annotation: Annotation
    enum CodingKeys: String, CodingKey { case baseRevision = "base_revision", annotation }
}
struct DatasetClassesRequest: Encodable {
    var baseRevision: Int
    var classes: [DatasetClass]
    enum CodingKeys: String, CodingKey { case baseRevision = "base_revision", classes }
}
enum DatasetFilter: String, CaseIterable {
    case all = "All images", unreviewed = "Needs review", reviewed = "Reviewed", empty = "No boxes"
}
