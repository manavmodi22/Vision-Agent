import SwiftUI

struct AgentPlanCard: View {
    @EnvironmentObject var model: WorkspaceModel
    let plan: PlatformBuildPlan
    let execution: PlatformExecution?
    @NativeState<Bool> private var details = false
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                Label("Build plan", systemImage: "list.bullet.rectangle").font(.callout.weight(.semibold))
                Spacer(); Text("Revision \(plan.revision)").font(.caption).foregroundStyle(Studio.muted)
            }
            ForEach(Array(plan.candidates.enumerated()), id: \.offset) { index, candidate in
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(index + 1). \(candidate.name)").font(.caption.weight(.medium))
                    ForEach(Array(plan.modelSelections(for: index).enumerated()), id: \.offset) { _, selection in
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Model to test: \(selection.modelID)").font(.caption2).textSelection(.enabled)
                            Text("Proposed reason: \(selection.proposedReason)").font(.caption2).foregroundStyle(Studio.muted).lineLimit(2)
                        }
                    }
                    ForEach(Array(plan.metrics.filter { $0.candidateIndex == index }.enumerated()), id: \.offset) { _, metric in
                        Text("\(PlatformPresentation.label(metric.metric)) \(metric.targetLabel)").font(.caption2).foregroundStyle(Studio.muted)
                    }
                }
            }
            if let execution {
                HStack { PlatformStatus(status: execution.status); Text(PlatformPresentation.label(execution.phase)).font(.caption2).foregroundStyle(Studio.muted); Spacer() }
                if let error = execution.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                if execution.planID != plan.id || execution.planHash != plan.contentHash {
                    Text("This execution belongs to another plan revision.").font(.caption).foregroundStyle(.orange)
                }
            }
            if !plan.humanCheckpoints.isEmpty {
                Text("\(plan.humanCheckpoints.count) human checkpoints · \(plan.experiments.count) bounded experiments").font(.caption2).foregroundStyle(Studio.muted)
            }
            HStack { Text("Saved \(PlatformPresentation.time(plan.createdAt))").font(.caption2).foregroundStyle(Studio.muted); Spacer(); Button("Review plan") { details = true }.font(.caption) }
        }.padding(15).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Studio.accent.opacity(0.18)))
            .sheet(isPresented: $details) {
                AgentPlanDetails(plan: plan, execution: execution) { capabilityID in
                    details = false; model.capabilityFocus = capabilityID; model.section = "Capabilities"
                }
            }
    }
}

struct AgentPlanDetails: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<Bool> private var inspectingOptions = false
    let plan: PlatformBuildPlan
    let execution: PlatformExecution?
    let inspectCapability: (String) -> Void
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Build plan · revision \(plan.revision)").font(.title2.weight(.semibold))
                    Text("Saved plan revisions remain immutable during execution.").font(.caption).foregroundStyle(Studio.muted)
                }
                Spacer(); Button("Done") { dismiss() }
            }.padding(24)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Text(plan.goal).font(.title3).textSelection(.enabled)
                    if let execution { HStack { PlatformStatus(status: execution.status); Text(PlatformPresentation.label(execution.phase)).font(.caption).foregroundStyle(Studio.muted) } }
                    section("Assumptions", values: plan.assumptions)
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Candidate workflows & evaluation targets").font(.headline)
                        ForEach(Array(plan.candidates.enumerated()), id: \.offset) { index, candidate in
                            VStack(alignment: .leading, spacing: 9) {
                                Text("Candidate \(index + 1) · \(candidate.name)").font(.callout.weight(.semibold))
                                ForEach(Array(plan.modelSelections(for: index).enumerated()), id: \.offset) { _, selection in
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text("Model to test: \(selection.modelID)").font(.callout.weight(.medium)).textSelection(.enabled)
                                        Text("Proposed reason: \(selection.proposedReason)").font(.callout).textSelection(.enabled)
                                        Text("This is a proposed test choice, not measured quality or an approved winner.").font(.caption2).foregroundStyle(Studio.muted)
                                        Text("Adapter: \(selection.adapterID) · Capability: \(selection.capabilityID)").font(.caption2).foregroundStyle(Studio.muted).textSelection(.enabled)
                                        Text("Options snapshot: \(selection.optionsSnapshotID)").font(.system(size: 9, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled)
                                    }.padding(.vertical, 5)
                                }
                                Text(candidate.blocks.map { PlatformPresentation.label($0.type) }.joined(separator: " → ")).font(.caption).foregroundStyle(Studio.muted)
                                ForEach(Array(plan.metrics.filter { $0.candidateIndex == index }.enumerated()), id: \.offset) { _, metric in
                                    Text("Target: \(PlatformPresentation.label(metric.metric)) \(metric.targetLabel)").font(.callout)
                                }
                                StructuredDetail(title: "Workflow specification", value: candidate)
                            }.padding(14).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                        if plan.planningOptionsArtifactID != nil {
                            Button("Inspect model options considered") { inspectingOptions = true }.disabled(!model.supervisor.connected)
                        }
                    }
                    VStack(alignment: .leading, spacing: 9) {
                        Text("Required capabilities").font(.headline)
                        if plan.requiredCapabilities.isEmpty { Text("No capability requirements recorded.").font(.caption).foregroundStyle(Studio.muted) }
                        ForEach(plan.requiredCapabilities, id: \.self) { id in Button { inspectCapability(id) } label: { Label(id, systemImage: "arrow.up.right.square").font(.callout) }.buttonStyle(.link) }
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Proposed experiments").font(.headline)
                        ForEach(plan.experiments) { experiment in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(PlatformPresentation.label(experiment.phase)).font(.caption.weight(.semibold))
                                Text(experiment.description).font(.callout)
                                Text("Allowed tools: \(experiment.allowedTools.joined(separator: ", "))").font(.caption2).foregroundStyle(Studio.muted)
                            }.padding(12).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 6))
                        }
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Human checkpoints").font(.headline)
                        ForEach(plan.humanCheckpoints) { checkpoint in
                            HStack(alignment: .top, spacing: 10) {
                                Image(systemName: "person.crop.circle").foregroundStyle(Studio.muted)
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(checkpoint.description).font(.callout)
                                    Text("\(PlatformPresentation.label(checkpoint.phase)) · \(checkpoint.requiresApproval ? "Human approval required" : "Human input required")").font(.caption2).foregroundStyle(Studio.muted)
                                }
                            }
                        }
                    }
                    section("Stop conditions", values: plan.stopConditions)
                    if !plan.skills.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Versioned playbooks").font(.headline)
                            ForEach(plan.skills) { skill in
                                VStack(alignment: .leading, spacing: 4) { Text("\(skill.id) · \(skill.version)").font(.caption); Text(skill.sha256).font(.system(size: 9, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled) }
                            }
                        }
                    }
                    VStack(alignment: .leading, spacing: 7) {
                        Text("Revision provenance").font(.headline)
                        Text(plan.revisionReason).font(.caption)
                        Text("Plan \(plan.id)\nSHA-256 \(plan.contentHash)").font(.system(size: 10, design: .monospaced)).textSelection(.enabled)
                        if let parent = plan.parentPlanID { Text("Previous plan: \(parent)").font(.caption2).foregroundStyle(Studio.muted) }
                        StructuredDetail(title: "Dataset, model and settings snapshot", value: plan.snapshot)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading).padding(24)
            }
        }.frame(width: 760, height: 680).background(Studio.background)
            .sheet(isPresented: $inspectingOptions) {
                if let artifactID = plan.planningOptionsArtifactID { PlatformArtifactView(projectID: plan.projectID, artifactID: artifactID, client: model.client) }
            }
    }
    private func section(_ title: String, values: [String]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            if values.isEmpty { Text("None recorded.").font(.caption).foregroundStyle(Studio.muted) }
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in Text("• " + value).font(.callout).textSelection(.enabled) }
        }
    }
}
