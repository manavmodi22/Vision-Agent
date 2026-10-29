import SwiftUI
import AppKit

struct AgentTimelineView: View {
    @EnvironmentObject var model: WorkspaceModel
    @ObservedObject var agent: AgentWorkspaceStore
    @NativeState<String?> private var artifactID: String? = nil
    @NativeState<Bool> private var expanded = false
    private var events: [PlatformToolEvent] { PlatformTimeline.ordered(agent.build?.toolEvents ?? []) }
    private var activeCalls: Set<String> { agent.running ? PlatformTimeline.activeCallIDs(events) : [] }
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack { Label("Agent activity", systemImage: "list.bullet.indent").font(.callout.weight(.semibold)); Spacer() }
            if events.isEmpty {
                Text("No tool actions have been recorded for this build yet.").font(.caption).foregroundStyle(Studio.muted)
            } else {
                if let event = PlatformTimeline.currentEvent(events, running: agent.running) { currentAction(event) }
                DisclosureGroup("All \(events.count) recorded events", isExpanded: $expanded) {
                    VStack(alignment: .leading, spacing: 0) { ForEach(events) { event in eventRow(event) } }.padding(.top, 12)
                }.font(.caption).foregroundStyle(Studio.muted)
            }
        }.padding(15).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 9))
            .sheet(isPresented: Binding(get: { artifactID != nil }, set: { if !$0 { artifactID = nil } })) {
                if let artifactID { PlatformArtifactView(projectID: agent.projectID, artifactID: artifactID, client: agent.client) }
            }
    }
    private func currentAction(_ event: PlatformToolEvent) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .top, spacing: 8) {
                if event.stage == "started" && activeCalls.contains(event.callID) { ProgressView().controlSize(.mini) }
                Text(PlatformPresentation.activityName(event)).font(.callout.weight(.medium))
                Spacer(minLength: 0)
                Text(PlatformPresentation.label(event.stage)).font(.caption).foregroundStyle(PlatformPresentation.color(event.stage))
            }
            HStack { Text(AgentConversation.phaseLabel(event.phase)); Spacer(); if let milliseconds = event.durationMs { Text(PlatformPresentation.duration(milliseconds / 1000)) } else { Text(PlatformPresentation.time(event.at)) } }.font(.caption2).foregroundStyle(Studio.muted)
            if let error = event.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
        }
    }
    private func eventRow(_ event: PlatformToolEvent) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 6) {
                if event.stage == "started" && activeCalls.contains(event.callID) { ProgressView().controlSize(.mini).frame(width: 15, height: 15) }
                else { Circle().fill(PlatformPresentation.color(event.stage)).frame(width: 6, height: 6).frame(width: 15, height: 15) }
                Rectangle().fill(Studio.muted.opacity(0.2)).frame(width: 1)
            }.frame(width: 15)
            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .firstTextBaseline) {
                    Text(event.name).font(.caption.weight(.medium)).textSelection(.enabled)
                    Spacer(minLength: 4)
                    Text(PlatformPresentation.label(event.stage)).font(.caption2).foregroundStyle(PlatformPresentation.color(event.stage))
                }
                Text("\(event.kind == "llm" ? "Model" : "Tool") · \(AgentConversation.phaseLabel(event.phase)) · #\(event.sequence)").font(.caption2).foregroundStyle(Studio.muted)
                HStack(spacing: 8) {
                    Text(PlatformPresentation.time(event.at))
                    if let milliseconds = event.durationMs { Text("· \(PlatformPresentation.duration(milliseconds / 1000))") }
                    if let cost = event.costUSD { Text(String(format: "· $%.4f", cost)) }
                }.font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted)
                if let identity = event.modelIdentity { Text(identity).font(.system(size: 9, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled) }
                if let error = event.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled).fixedSize(horizontal: false, vertical: true) }
                HStack {
                    Button("Input") { artifactID = event.inputArtifactID }
                    if let output = event.outputArtifactID { Button("Output") { artifactID = output } }
                }.font(.caption2).disabled(!model.supervisor.connected)
            }.padding(.bottom, 12)
        }
    }
}

struct PlatformArtifactView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var model: WorkspaceModel
    let projectID: String
    let artifactID: String
    let client: EngineClient
    @NativeState<PlatformArtifactContent?> private var result: PlatformArtifactContent? = nil
    @NativeState<Bool> private var loading = false
    @NativeState<String?> private var error: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text(result?.artifact.title ?? "Recorded artifact").font(.title2.weight(.semibold)); Spacer(); Button("Done") { dismiss() } }
            if loading { ProgressView("Loading recorded content…") }
            if let error { Text(error).font(.callout).foregroundStyle(.orange).textSelection(.enabled); Button("Retry") { Task { await load() } }.disabled(loading || !model.supervisor.connected) }
            if let result {
                HStack { Text(PlatformPresentation.label(result.artifact.kind)); Spacer(); Text(ByteCountFormatter.string(fromByteCount: Int64(result.artifact.sizeBytes), countStyle: .file)); Text(PlatformPresentation.time(result.artifact.createdAt)) }.font(.caption).foregroundStyle(Studio.muted)
                Text("Recorded SHA-256: \(result.artifact.sha256)").font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled)
                ScrollView([.horizontal, .vertical]) { Text(PlatformPresentation.json(result.content)).font(.system(size: 11, design: .monospaced)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(14) }.background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8))
                HStack { Text(result.artifact.kind == "planning_options" ? "Read-only planning snapshot" : "Read-only execution evidence").font(.caption).foregroundStyle(Studio.muted); Spacer(); Button("Copy JSON") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(PlatformPresentation.json(result.content), forType: .string) } }
            }
            Spacer(minLength: 0)
        }.padding(24).frame(width: 760, height: 600).background(Studio.background).task { await load() }
    }
    private func load() async {
        guard model.supervisor.connected else { error = model.supervisor.status; return }
        guard !loading else { return }; loading = true; error = nil
        defer { loading = false }
        do { result = try await client.request("GET", "/projects/\(projectID)/build/artifacts/\(PlatformTimeline.pathComponent(artifactID))") }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
    }
}
