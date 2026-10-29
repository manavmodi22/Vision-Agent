import Foundation
import SwiftUI

enum PlatformPresentation {
    static func activityName(_ event: PlatformToolEvent) -> String {
        if event.kind == "llm" { return event.phase.contains("refin") ? "Planning your changes" : "Interpreting your request" }
        let names = [
            "build_context": "Reading your app context", "build_refinement_context": "Reading the current workflow",
            "build_refine": "Processing your requested changes", "build_prepare_review": "Preparing examples for review",
            "build_propose_labels": "Preparing label suggestions", "suggest_labels": "Preparing label suggestions",
            "pipeline_run": "Testing your workflow", "pipeline_validate": "Checking workflow validity",
            "eval_run": "Measuring workflow results", "eval_create": "Preparing evaluation examples",
            "frames_sample": "Selecting example frames", "media_import": "Importing your examples",
            "dataset_context": "Reading your examples", "blocks_list": "Checking available workflow tools",
            "block_schema": "Checking tool requirements", "build_train": "Training a local detector",
            "build_operate": "Running your approved application", "review_queue": "Reading examples needing review",
            "events_query": "Reading recorded evidence", "evidence_context": "Reading evidence context",
            "evidence_execute": "Checking your question against evidence", "capabilities_list": "Checking available capabilities"
        ]
        return names[event.name] ?? "Agent action"
    }
    static func label(_ value: String) -> String {
        let known = ["available_to_install": "Available to install", "unchecked": "Not verified",
                     "awaiting_review": "Waiting for review", "stale": "Out of date",
                     "started": "Started", "completed": "Completed", "succeeded": "Completed"]
        return known[value] ?? value.replacingOccurrences(of: "_", with: " ").capitalized
    }
    static func date(_ value: String) -> Date? {
        let format = ISO8601DateFormatter(); format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return format.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    }
    static func time(_ value: String?) -> String {
        guard let value else { return "Not recorded" }
        return date(value)?.formatted(date: .omitted, time: .standard) ?? value
    }
    static func duration(_ seconds: Double?) -> String {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return "—" }
        return seconds < 1 ? String(format: "%.0f ms", seconds * 1000) : String(format: "%.1f s", seconds)
    }
    static func json<T: Encodable>(_ value: T) -> String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        return (try? encoder.encode(value)).flatMap { String(data: $0, encoding: .utf8) } ?? "Unavailable"
    }
    static func color(_ status: String) -> Color {
        switch status {
        case "ready", "completed", "succeeded", "pass": return Studio.accent
        case "running", "started": return .cyan
        case "failed", "error", "fail": return .red
        case "blocked", "stale", "interrupted", "paused": return .orange
        default: return Studio.muted
        }
    }
}

struct PlatformStatus: View {
    let status: String
    var body: some View {
        HStack(spacing: 5) {
            if status == "running" { ProgressView().controlSize(.mini) }
            else { Circle().fill(PlatformPresentation.color(status)).frame(width: 5, height: 5) }
            Text(PlatformPresentation.label(status)).font(.caption2.weight(.medium))
        }.foregroundStyle(PlatformPresentation.color(status))
    }
}

struct StructuredDetail<Value: Encodable>: View {
    let title: String
    let value: Value
    var body: some View {
        DisclosureGroup(title) {
            ScrollView([.horizontal, .vertical]) {
                Text(PlatformPresentation.json(value)).font(.system(size: 10, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(10)
            }.frame(maxHeight: 220).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 6))
        }.font(.caption).foregroundStyle(Studio.muted)
    }
}
