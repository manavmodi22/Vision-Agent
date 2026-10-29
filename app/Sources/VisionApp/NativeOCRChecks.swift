import Foundation
import Vision

enum NativeOCRChecks {
    static func run() throws -> Int {
        let request = VisionBridge.textRequest()
        guard request.recognitionLanguages == ["en-US"], request.automaticallyDetectsLanguage == false else {
            throw EngineError.protocolError("OCR request must honor the implemented en-US-only policy")
        }
        guard request.recognitionLevel == .accurate, request.usesLanguageCorrection == false else {
            throw EngineError.protocolError("OCR must preserve accurate raw code recognition")
        }
        guard try request.supportedRecognitionLanguages().contains("en-US") else {
            throw EngineError.protocolError("This native OCR revision does not support the required en-US language")
        }
        return 3
    }
}
