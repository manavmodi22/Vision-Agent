import Foundation

enum EvaluationContractChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Evaluation check failed: " + message) }; checks += 1
        }
        let reading = Pipeline(name: "Read custom labels", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "reader", type: "barcode")])
        try require(EvaluationPresentation.isReading(reading), "custom barcode graph exposes expected text review")
        var ocr = reading; ocr.blocks[0].type = "ocr"
        try require(EvaluationPresentation.isReading(ocr), "OCR block exposes expected text review")
        var detector = reading; detector.blocks[0].type = "detect"
        try require(!EvaluationPresentation.isReading(detector) && EvaluationPresentation.hasDetector(detector), "object graph does not become a reading task from its project name")
        let provenance = JSONValue.object(["status": .string("model_hypothesis"), "model": .string("native-reader")])
        let original = Annotation(imagePath: "/project/media/example.png", detections: [], reviewed: true, expectedTexts: ["OLD"], proposal: provenance)
        let updated = ExpectedTextEditing.update(original, values: ExpectedTextEditing.values(" SKU-1\nCODE-2\n"))
        try require(updated.expectedTexts == [" SKU-1", "CODE-2"] && !updated.reviewed, "reading edits preserve literal whitespace and require new review")
        try require(updated.proposal == provenance && updated.imagePath == original.imagePath, "reading edits preserve actual proposal provenance and source")
        try require(ExpectedTextEditing.update(original, values: original.expectedTexts) == original, "unchanged expected values retain explicit review")
        var composed = original; composed.expectedTexts = ["é"]; composed.reviewed = false
        let decomposed = ExpectedTextEditing.update(composed, values: ["e\u{301}"])
        try require(composed != decomposed && decomposed.expectedTexts[0].utf8.count == 3, "literal Unicode corrections remain dirty even when Swift strings are canonically equivalent")
        try require(ExpectedTextEditing.same([" A  B "], ExpectedTextEditing.values(" A  B \n")), "manual expected values preserve leading, trailing and repeated spaces")
        let evaluation = Evaluation(precision: 0.8, recall: 0.6, countMae: 1.25, passed: false, metric: "count_mae", target: 0.5, sampleCount: 10, failures: [], specHash: "spec", datasetHash: "data", textAccuracy: nil)
        try require(EvaluationPresentation.measuredValue(evaluation) == 1.25 && EvaluationPresentation.target(evaluation).hasPrefix("≤"), "count error uses its measured value and lower-is-better target")
        var textEvaluation = evaluation; textEvaluation.metric = "text_accuracy"
        try require(EvaluationPresentation.measuredValue(textEvaluation) == nil && EvaluationPresentation.format(nil, metric: "text_accuracy") == "Not reported", "missing reading scores are never replaced with zero")
        var readingWire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(textEvaluation)).object
        readingWire["character_error_rate"] = .number(1.5); readingWire["word_error_rate"] = .null
        readingWire["text_normalization"] = .string("unicode_casefold_whitespace")
        readingWire["text_error_counts"] = .object(["character_edits": .number(3), "reference_characters": .number(2), "word_edits": .null])
        let rates = try JSONDecoder().decode(Evaluation.self, from: JSONEncoder().encode(readingWire))
        try require(rates.characterErrorRate == 1.5 && rates.wordErrorRate == nil && rates.textErrorCounts?["character_edits"] == 3, "text error rates retain insertions above 100 percent and undefined values")
        try require(evaluation.characterErrorRate == nil && evaluation.wordErrorRate == nil, "historical evaluation has no invented edit rates")
        let failure = EvaluatedFailure(.object(["image_path": .string("/one/frame.png"), "expected_texts": .array([]), "observed_texts": .array([.string("X")])]), index: 0)
        try require(failure.texts("expected_texts") == [] && failure.texts("observed_texts") == ["X"] && failure.number("false_negatives") == nil, "failure detail distinguishes empty ground truth from missing numeric evidence")
        let images = [DatasetImage(id: "first", imagePath: "/one/frame.png", width: 10, height: 10, reviewed: false, annotationCount: 0, split: "validation"), DatasetImage(id: "second", imagePath: "/two/frame.png", width: 10, height: 10, reviewed: false, annotationCount: 0, split: "validation")]
        try require(EvaluationPresentation.exactImage(path: "/two/frame.png", images: images)?.id == "second", "failure action resolves exact image instead of matching a duplicate filename")
        try require(EvaluationPresentation.exactImage(path: "/missing/frame.png", images: images) == nil, "removed failure image cannot open an unrelated frame")
        try require(AgentReviewContext.preferredImage(path: "/two/frame.png", images: images)?.id == "second", "contextual correction opens the displayed image exactly")
        try require(AgentReviewContext.preferredImage(path: "/missing/frame.png", images: images) == nil, "missing contextual image never falls back to a different example")
        try require(AgentReviewContext.preferredImage(path: nil, images: images)?.id == "first", "review checkpoint opens the first unreviewed example without changing review")
        let unconfirmed = try JSONDecoder().decode(ZonesResponse.self, from: Data("{\"zones\":[{\"id\":\"A\",\"polygon\":[[0,0],[1,0],[1,1]]}],\"confirmed\":false,\"origin\":\"unconfirmed\"}".utf8))
        try require(unconfirmed.confirmed == false && unconfirmed.origin == "unconfirmed", "legacy region geometry remains explicitly unconfirmed")
        let legacy = try JSONDecoder().decode(ZonesResponse.self, from: Data("{\"zones\":[]}".utf8))
        try require(legacy.confirmed != true, "absent zone provenance does not confer confirmation")
        return checks
    }
}
