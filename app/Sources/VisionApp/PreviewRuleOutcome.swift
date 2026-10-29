import SwiftUI

struct PreviewEventDescription {
    let title: String
    let details: [String]
    init(_ event: JSONValue) {
        let fields = event.object
        let type = fields["type"]?.string ?? fields["event_type"]?.string ?? "event"
        switch type {
        case "label_check":
            if case .bool(let matched) = fields["matched"] { title = matched ? "Text matched" : "Text did not match" }
            else { title = "Text comparison event" }
        case "count_rule": title = "Count rule triggered"
        case "vlm_judgement": title = "Vision model judgement"
        default: title = PlatformPresentation.label(type)
        }
        var rows: [String] = []
        for key in ["message", "reason"] {
            if let value = fields[key]?.string, !value.isEmpty { rows.append(value) }
        }
        if let expected = fields["expected"]?.string { rows.append("Expected: " + expected) }
        if case .array(let observed) = fields["observed"] {
            let values = observed.compactMap(\.string)
            rows.append("Observed: " + (values.isEmpty ? "(no text)" : values.joined(separator: " · ")))
        }
        if let when = fields["when"]?.string { rows.append("Condition: " + when) }
        if let zone = fields["zone"]?.string { rows.append("Region: " + zone) }
        if case .number(let count) = fields["count"] { rows.append(String(format: "Count: %.0f", count)) }
        if case .number(let held) = fields["held_s"] { rows.append(String(format: "Held for %.1f s", held)) }
        if let label = fields["label"]?.string { rows.append("Label: " + label) }
        details = rows
    }
}

enum PreviewOutcomePresentation {
    static func hasEventSink(_ pipeline: Pipeline?) -> Bool { pipeline?.blocks.contains { $0.type == "sink_event" } == true }
    static func summary(_ events: [JSONValue]) -> String {
        events.isEmpty ? "No event for this sample." : "\(events.count) event\(events.count == 1 ? "" : "s") emitted for this sample."
    }
    static func recordingLabel(recorded: Bool) -> String {
        recorded ? "Approved run — event recording enabled" : "Preview only — no events recorded"
    }
}

struct PreviewRuleOutcome: View {
    let events: [JSONValue]
    let recorded: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack { Text("Rule outcome").font(.callout.weight(.semibold)); Spacer(); Text(PreviewOutcomePresentation.recordingLabel(recorded: recorded)).font(.caption2).foregroundStyle(Studio.muted) }
            Text(PreviewOutcomePresentation.summary(events)).font(.callout)
            ForEach(Array(events.enumerated()), id: \.offset) { _, event in
                let description = PreviewEventDescription(event)
                VStack(alignment: .leading, spacing: 5) {
                    Text(description.title).font(.caption.weight(.medium))
                    ForEach(Array(description.details.enumerated()), id: \.offset) { _, detail in Text(detail).font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled) }
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 6))
            }
        }.padding(13).background(Studio.raised.opacity(0.5)).clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
