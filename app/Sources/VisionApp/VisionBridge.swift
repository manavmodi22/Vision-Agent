import Foundation
import Vision
import ImageIO

struct NativeReadings: Codable { var texts: [String]; var barcodes: [String] }
struct NativeReadingsV2: Codable {
    var schemaVersion = 2
    var requestPolicy = VisionBridge.requestPolicyVersion
    var coordinateSpace = "normalized_top_left"
    var inputSize: [Int]
    var texts: [String]
    var barcodes: [String]
    var readings: [ReadingObservation]
    var warnings: [String]
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", requestPolicy = "request_policy", coordinateSpace = "coordinate_space"
        case inputSize = "input_size", texts, barcodes, readings, warnings
    }
}

enum VisionBridge {
    static let requestPolicyVersion = "apple-vision-en-us-v2"
    static func textRequest() -> VNRecognizeTextRequest {
        let text = VNRecognizeTextRequest()
        text.recognitionLevel = .accurate
        text.recognitionLanguages = ["en-US"]
        text.automaticallyDetectsLanguage = false
        text.usesLanguageCorrection = false
        return text
    }
    static func analyze(path: String) throws -> NativeReadings {
        let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:])
        let text = textRequest()
        let barcode = VNDetectBarcodesRequest()
        try handler.perform([text, barcode])
        return NativeReadings(texts: text.results?.compactMap { $0.topCandidates(1).first?.string } ?? [],
                              barcodes: barcode.results?.compactMap(\.payloadStringValue) ?? [])
    }
    static func analyzeRich(path: String) throws -> NativeReadingsV2 {
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
            throw EngineError.protocolError("The input image could not be decoded")
        }
        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
        let rawOrientation = (properties?[kCGImagePropertyOrientation] as? NSNumber)?.uint32Value ?? 1
        guard let orientation = CGImagePropertyOrientation(rawValue: rawOrientation) else {
            throw EngineError.protocolError("Unsupported image orientation")
        }
        let rotated = [5, 6, 7, 8].contains(rawOrientation)
        let size = rotated ? [image.height, image.width] : [image.width, image.height]
        guard size.allSatisfy({ (1...32768).contains($0) }) else { throw EngineError.protocolError("Image dimensions exceed the reader contract") }
        let handler = VNImageRequestHandler(cgImage: image, orientation: orientation, options: [:])
        let text = textRequest(), barcode = VNDetectBarcodesRequest()
        try handler.perform([text, barcode])
        var readings: [ReadingObservation] = [], warnings: [String] = []
        func append(_ observation: VNRectangleObservation, value: String, kind: String, confidence: Double?, symbology: String?) throws {
            guard value.unicodeScalars.count <= 16384, readings.count < 10000 else { throw EngineError.protocolError("Reading output exceeds the observation limits") }
            let geometry = ReadingGeometry.fromVision([observation.topLeft, observation.topRight, observation.bottomRight, observation.bottomLeft])
            if geometry == nil && warnings.count < 20 { warnings.append("\(kind) observation \(readings.count): invalid or out-of-frame geometry omitted; text preserved.") }
            let score = confidence.flatMap { $0.isFinite && (0...1).contains($0) ? $0 : nil }
            readings.append(ReadingObservation(text: value, kind: kind, box: geometry?.box, polygon: geometry?.polygon,
                                               confidence: score, symbology: symbology))
        }
        for observation in text.results ?? [] {
            if let candidate = observation.topCandidates(1).first {
                try append(observation, value: candidate.string, kind: "ocr", confidence: Double(candidate.confidence), symbology: nil)
            }
        }
        for observation in barcode.results ?? [] {
            if let payload = observation.payloadStringValue {
                // Generic VNObservation confidence can be an unsupported sentinel; no decoding score is asserted.
                try append(observation, value: payload, kind: "barcode", confidence: nil, symbology: observation.symbology.rawValue)
            }
        }
        guard readings.reduce(0, { $0+$1.text.utf8.count }) <= 1024*1024 else { throw EngineError.protocolError("Reading text exceeds 1 MiB") }
        return NativeReadingsV2(inputSize: size, texts: readings.filter { $0.kind == "ocr" }.map(\.text),
                                barcodes: readings.filter { $0.kind == "barcode" }.map(\.text), readings: readings, warnings: warnings)
    }
    static func protocolVersion(arguments: [String]) -> Int? {
        if arguments.count == 3 { return 1 }
        if arguments.count == 5, arguments[3] == "--protocol", arguments[4] == "2" { return 2 }
        return nil
    }
    static func runIfRequested() -> Bool {
        guard CommandLine.arguments.count > 1, CommandLine.arguments[1] == "--analyze-image" else { return false }
        guard let version = protocolVersion(arguments: CommandLine.arguments) else {
            FileHandle.standardError.write(Data("Usage: VisionApp --analyze-image IMAGE [--protocol 2]\n".utf8)); exit(2)
        }
        do {
            let response = try CLIJSONOutput()
            if version == 2 { try response.emit(analyzeRich(path: CommandLine.arguments[2])) }
            else { try response.emit(analyze(path: CommandLine.arguments[2])) }
            exit(0)
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1)
        }
    }
}
