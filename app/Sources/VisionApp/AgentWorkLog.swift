import SwiftUI

struct AgentWorkLog: View {
    @ObservedObject var agent: AgentWorkspaceStore
    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack {
                Text("Agent work log").font(.callout.weight(.medium)); Spacer()
                if let build = agent.build { Text(AgentConversation.phaseLabel(build.running ? build.phase : build.status)).font(.caption).foregroundStyle(Studio.muted) }
            }
            if let build = agent.build, !build.log.isEmpty {
                ForEach(Array(build.log.suffix(16).enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .top, spacing: 10) {
                        Text(logTime(item.at)).font(.system(size: 9, design: .monospaced)).foregroundStyle(Studio.muted).frame(width: 55, alignment: .leading)
                        VStack(alignment: .leading, spacing: 3) { Text(AgentConversation.phaseLabel(item.phase)).font(.caption2).foregroundStyle(Studio.muted); Text(item.message).font(.caption).textSelection(.enabled) }
                    }
                }
            } else { Text("Actual steps and results will appear when the agent starts.").font(.caption).foregroundStyle(Studio.muted) }
            if let error = agent.error { Text(error).font(.caption2).foregroundStyle(.orange).textSelection(.enabled) }
        }.padding(14).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 9))
    }
    private func logTime(_ value: String) -> String {
        let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
        return date?.formatted(date: .omitted, time: .shortened) ?? String(value.suffix(8))
    }
}

struct WorkflowDetailsView: View {
    @EnvironmentObject var model: WorkspaceModel
    var body: some View {
        ScrollView { VStack(alignment: .leading, spacing: 16) {
            HStack { Text("Inspect or adjust the agent's workflow.").font(.callout).foregroundStyle(Studio.muted); Spacer(); Button("Back to Agent") { model.section = "Agent" } }
            PipelineInspector()
        }.padding(24) }
    }
}
