import Foundation
import Vision
import ImageIO

struct NativeReadings: Codable { var texts: [String]; var barcodes: [String] }

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
    static func runIfRequested() -> Bool {
        guard CommandLine.arguments.count > 1, CommandLine.arguments[1] == "--analyze-image" else { return false }
        guard CommandLine.arguments.count == 3 else {
            FileHandle.standardError.write(Data("Usage: VisionApp --analyze-image IMAGE\n".utf8)); exit(2)
        }
        do {
            let response = try CLIJSONOutput()
            let result = try analyze(path: CommandLine.arguments[2])
            try response.emit(result)
            exit(0)
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1)
        }
    }
}
