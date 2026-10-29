import Foundation

enum TextComparisonChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Text comparison check failed: " + message) }
            checks += 1
        }
        let legacyWire: [String: JSONValue] = ["image_path": .string("frame.png"), "detections": .array([]),
            "counts": .object([:]), "texts": .array([.string("XABC-990Y")]), "events": .array([]), "elapsed_ms": .number(10)]
        let legacy = try JSONDecoder().decode(FrameResult.self, from: JSONEncoder().encode(legacyWire))
        let pipeline = Pipeline(name: "Compare text", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "check", type: "match")])
        try require(legacy.comparisons == nil, "historical frames keep unavailable comparison evidence distinct from an empty result")
        try require(!TextComparisonPresentation.isVisible(frame: legacy, pipeline: nil), "historical text alone cannot invent a comparison")
        try require(TextComparisonPresentation.isVisible(frame: legacy, pipeline: pipeline), "known comparison workflow shows unavailable evidence for historical preview")

        let expected = " é  X "
        let decomposed = " e\u{301}  Х "
        var wire = legacyWire
        wire["comparisons"] = .array([
            .object(["block_id": .string("check"), "expected": .string(expected), "observed": .array([.string(decomposed), .string(decomposed)]),
                     "mode": .string("exact"), "matched": .bool(false)]),
            .object(["block_id": .string("sku"), "expected": .string("ABC-990"), "observed": .array([.string("XABC-990Y")]),
                     "mode": .string("contains"), "matched": .bool(true)])])
        let frame = try JSONDecoder().decode(FrameResult.self, from: JSONEncoder().encode(wire))
        guard let comparisons = frame.comparisons, comparisons.count == 2 else { throw EngineError.protocolError("Comparison fixture failed to decode") }
        try require(frame.events.isEmpty && TextComparisonPresentation.isVisible(frame: frame, pipeline: nil), "comparison results are visible with zero events and no pipeline context")
        try require(comparisons[0].blockID == "check" && comparisons[1].blockID == "sku", "separate match blocks retain separate observations")
        try require(comparisons[0].resultLabel == "Fail" && comparisons[1].resultLabel == "Pass", "result labels use engine Booleans without deriving outcomes from event presence")
        try require(comparisons[0].mode == .exact && comparisons[1].mode == .contains, "exact and substring comparison modes remain distinct")
        try require(Data(comparisons[0].expected.utf8) == Data(expected.utf8) && comparisons[0].observed.map { Data($0.utf8) } == [Data(decomposed.utf8), Data(decomposed.utf8)], "comparison decoding preserves raw Unicode, whitespace and duplicate observations")
        let restored = try JSONDecoder().decode(FrameResult.self, from: JSONEncoder().encode(frame))
        try require(restored.comparisons?[0].observed.map { Data($0.utf8) } == comparisons[0].observed.map { Data($0.utf8) }, "raw observed values survive a wire round trip")
        let canonical = TextComparison(blockID: "unicode", expected: "é", observed: ["e\u{301}"], mode: .exact, matched: false)
        try require(canonical.expected == canonical.observed[0] && canonical.resultLabel == "Fail", "Swift canonical equality never overwrites the engine's literal comparison result")
        let empty = TextComparison(blockID: "missing", expected: "ABC", observed: [], mode: .exact, matched: false)
        try require(empty.observed.isEmpty && empty.resultLabel == "Fail", "missing recognition retains an explicit empty observation rather than an invented expected value")
        var invalidMode = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(empty)).object
        invalidMode["mode"] = .string("fuzzy")
        var rejected = false
        do { _ = try JSONDecoder().decode(TextComparison.self, from: JSONEncoder().encode(invalidMode)) } catch { rejected = true }
        try require(rejected, "unsupported comparison mode cannot render a misleading known mode")

        var selectionWire: [String: JSONValue] = ["candidate_index": .number(0), "capability_id": .string("model.apple-vision"),
            "model_id": .string("apple-vision"), "adapter_id": .string("apple-vision"), "proposed_reason": .string("Test the installed reader"),
            "options_snapshot_id": .string("snapshot"), "status": .string("proposed")]
        let candidateSelection = try JSONDecoder().decode(PlanCandidateModelSelection.self, from: JSONEncoder().encode(selectionWire))
        try require(candidateSelection.blockID == nil && candidateSelection.modelTestLabel == "Model to test: apple-vision", "historical candidate selections preserve their previous labels")
        selectionWire["block_id"] = .string("ocr_left")
        let blockSelection = try JSONDecoder().decode(PlanCandidateModelSelection.self, from: JSONEncoder().encode(selectionWire))
        try require(blockSelection.blockID == "ocr_left" && blockSelection.modelTestLabel == "Block ocr_left · model to test: apple-vision", "new model proposals identify their inference block")
        let selectionOutput = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(blockSelection)).object
        try require(selectionOutput["block_id"] == .string("ocr_left") && blockSelection.candidateIndex == 0, "block selection encoding preserves both candidate and node ownership")
        return checks
    }
}
