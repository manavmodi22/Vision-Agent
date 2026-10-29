import Foundation

/// Presentation derives only from registered block types and measured evidence.
enum EvaluationPresentation {
    static func isReading(_ pipeline: Pipeline?) -> Bool { pipeline?.blocks.contains { ["ocr", "barcode"].contains($0.type) } == true }
    static func hasDetector(_ pipeline: Pipeline?) -> Bool { pipeline?.blocks.contains { ["detect", "detect_open_vocab"].contains($0.type) } == true }
    static func metricName(_ metric: String) -> String {
        switch metric { case "count_mae": return "Count MAE"; case "text_accuracy": return "Text accuracy"; case "precision": return "Precision"; case "recall": return "Recall"; default: return metric }
    }
    static func measuredValue(_ evaluation: Evaluation) -> Double? {
        switch evaluation.metric { case "count_mae": return evaluation.countMae; case "precision": return evaluation.precision; case "recall": return evaluation.recall; case "text_accuracy": return evaluation.textAccuracy; default: return nil }
    }
    static func format(_ value: Double?, metric: String) -> String {
        guard let value else { return "Not reported" }
        return ["precision", "recall", "text_accuracy"].contains(metric) ? String(format: "%.1f%%", value * 100) : String(format: "%.3f", value)
    }
    static func target(_ evaluation: Evaluation) -> String {
        (evaluation.metric == "count_mae" ? "≤ " : "≥ ") + format(evaluation.target, metric: evaluation.metric)
    }
    static func exactImage(path: String, images: [DatasetImage]) -> DatasetImage? {
        guard path.hasPrefix("/") else { return nil }
        let target = URL(fileURLWithPath: path).standardizedFileURL.resolvingSymlinksInPath()
        return images.first { URL(fileURLWithPath: $0.imagePath).standardizedFileURL.resolvingSymlinksInPath() == target }
    }
}
struct EvaluatedFailure: Identifiable {
    let index: Int
    let fields: [String: JSONValue]
    init(_ value: JSONValue, index: Int) { self.index = index; fields = value.object }
    var id: String { "\(index)-\(imagePath ?? "missing")" }
    var imagePath: String? { fields["image_path"]?.string }
    func number(_ key: String) -> Double? { if case .number(let value) = fields[key] { return value }; return nil }
    func texts(_ key: String) -> [String]? { if case .array(let values) = fields[key] { return values.compactMap(\.string) }; return nil }
    var error: String? { fields["error"]?.string }
}

enum ExpectedTextEditing {
    static func values(_ text: String) -> [String] { text.components(separatedBy: .newlines).filter { !$0.isEmpty } }
    static func same(_ lhs: [String], _ rhs: [String]) -> Bool { lhs.map { Data($0.utf8) } == rhs.map { Data($0.utf8) } }
    static func update(_ annotation: Annotation, values: [String]) -> Annotation {
        guard !same(annotation.expectedTexts, values) else { return annotation }
        var updated = annotation; updated.expectedTexts = values; updated.reviewed = false; return updated
    }
}
