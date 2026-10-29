import Foundation

enum PreviewOutcomeChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Preview outcome check failed: " + message) }; checks += 1
        }
        let matched: JSONValue = .object(["type": .string("label_check"), "matched": .bool(true), "expected": .string("ABC-990"), "observed": .array([.string("ABC-990")])])
        let description = PreviewEventDescription(matched)
        try require(description.title == "Text matched" && description.details == ["Expected: ABC-990", "Observed: ABC-990"], "actual match output keeps its literal expected and observed values")
        let mismatch = PreviewEventDescription(.object(["type": .string("label_check"), "matched": .bool(false), "expected": .string("ABC-990"), "observed": .array([.string("XABC-990Y")])]))
        try require(mismatch.title == "Text did not match" && mismatch.details.contains("Observed: XABC-990Y"), "UI does not reinterpret a reported mismatch as a substring match")
        try require(PreviewEventDescription(.object(["type": .string("label_check")])).title == "Text comparison event", "missing match evidence does not default to a success or failure")
        try require(PreviewOutcomePresentation.summary([]) == "No event for this sample." && PreviewOutcomePresentation.summary([matched]) == "1 event emitted for this sample.", "event counts come only from emitted events and zero does not imply accuracy")
        let count = PreviewEventDescription(.object(["type": .string("count_rule"), "zone": .string("A"), "count": .number(3), "when": .string("count >= 2"), "held_s": .number(4)]))
        try require(count.title == "Count rule triggered" && count.details.contains("Condition: count >= 2") && count.details.contains("Count: 3") && count.details.contains("Held for 4.0 s"), "count rule description preserves actual trigger evidence")
        let reason = PreviewEventDescription(.object(["type": .string("quality_event"), "message": .string("Review this carton"), "reason": .string("Visible tear")]))
        try require(reason.title == "Quality Event" && reason.details == ["Review this carton", "Visible tear"], "message and reason are actual event fields")
        let sink = Pipeline(name: "Reading", specVersion: "0.1", inputs: [:], blocks: [PipelineBlock(id: "reader", type: "ocr"), PipelineBlock(id: "event", type: "sink_event")])
        try require(PreviewOutcomePresentation.hasEventSink(sink) && EvaluationPresentation.isReading(sink) && !EvaluationPresentation.hasDetector(sink), "reading event pipeline exposes outcomes without claiming object detection")
        try require(PreviewOutcomePresentation.recordingLabel(recorded: false) == "Preview only — no events recorded" && PreviewOutcomePresentation.recordingLabel(recorded: true) == "Approved run — event recording enabled", "preview and approved recorded results are not mislabeled")
        return checks
    }
}
