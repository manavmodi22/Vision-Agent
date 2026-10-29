import SwiftUI

struct ProvisioningSheet: View {
    @EnvironmentObject var model: WorkspaceModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var store: ProvisioningStore
    let onFinished: () async -> Void
    init(client: EngineClient, option: ProvisioningOption, onFinished: @escaping () async -> Void) {
        _store = StateObject(wrappedValue: ProvisioningStore(client: client, option: option)); self.onFinished = onFinished
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(store.plan?.name ?? store.option.name).font(.title2.weight(.semibold))
                    Text("Review model installation and current execution readiness.").font(.caption).foregroundStyle(Studio.muted)
                }
                Spacer()
                Button("Close") { dismiss() }
            }.padding(22)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let job = store.job { jobSection(job) }
                    if let plan = store.plan { planSection(plan) }
                    else if store.busy { HStack { ProgressView().controlSize(.small); Text("Loading the review plan…").font(.callout) } }
                    if let previous = store.previousJob {
                        DisclosureGroup("Previous attempt · \(PlatformPresentation.label(previous.status))") { jobSection(previous).padding(.top, 10) }.font(.caption)
                    }
                }.padding(22)
            }
            Divider()
            VStack(alignment: .leading, spacing: 9) {
                if let error = store.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                if let notice = store.notice { Text(notice).font(.caption).foregroundStyle(Studio.muted) }
                HStack {
                    if store.busy { ProgressView().controlSize(.small) }
                    Button("Refresh") { Task { if store.job != nil { await store.refreshJob() } else { await store.load() }; if store.job?.terminal == true { await onFinished() } } }
                        .disabled(store.busy || !model.supervisor.connected)
                    Spacer()
                    if let job = store.job {
                        if job.active { Text("You can close this sheet. The engine continues the approved job.").font(.caption).foregroundStyle(Studio.muted) }
                        else {
                            Button(job.status == "failed" || job.status == "interrupted" ? "Review retry plan" : "Review current validation plan") { Task { await store.reviewCurrentPlan() } }
                                .disabled(store.busy || !model.supervisor.connected)
                        }
                    } else if let plan = store.plan {
                        Button("Review updated plan") { Task { await store.reviewCurrentPlan() } }.disabled(store.busy || !model.supervisor.connected)
                        Button(ProvisioningPresentation.actionTitle(plan.action)) { Task { await store.startApproved(); if store.job?.terminal == true { await onFinished() } } }
                            .buttonStyle(.borderedProminent).disabled(!store.canApprove || !model.supervisor.connected)
                    }
                }
            }.padding(18)
        }.frame(width: 780, height: 720).background(Studio.background)
            .task { await store.load(); if store.job?.terminal == true { await onFinished() } }
            .task(id: store.job?.id) {
                guard let id = store.job?.id else { return }
                while store.job?.id == id, store.job?.active == true, !Task.isCancelled {
                    do { try await Task.sleep(for: .seconds(3)) } catch { return }
                    guard !Task.isCancelled else { return }
                    await store.refreshJob()
                }
                if !Task.isCancelled, store.job?.terminal == true { await onFinished() }
            }
    }
    private func planSection(_ plan: ProvisioningPlan) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("Plan for review").font(.headline); Spacer(); Text(PlatformPresentation.time(plan.createdAt)).font(.caption2).foregroundStyle(Studio.muted) }
            HStack(spacing: 24) {
                fact("Action", plan.action == "install" ? "Install + validate adapter" : "Validate existing installation")
                fact("Download", bytes(plan.totalDownloadBytes))
                fact("Time bound", "\(plan.maxDurationS) seconds")
            }
            Text(plan.readiness.reason).font(.callout).textSelection(.enabled)
            ForEach(plan.blockers, id: \.self) { Label($0, systemImage: "exclamationmark.triangle").font(.callout).foregroundStyle(.orange) }
            Text("Approval permits this plan’s download, local installation and bounded smoke test. The test checks adapter execution; it does not measure accuracy on your images or approve an application.").font(.caption).foregroundStyle(Studio.muted)
            requirements(plan)
            licensing(plan.license)
            VStack(alignment: .leading, spacing: 12) {
                Text("Pinned artifacts and sources").font(.callout.weight(.semibold))
                ForEach(Array(plan.artifacts.enumerated()), id: \.offset) { _, artifact in
                    VStack(alignment: .leading, spacing: 7) {
                        HStack { Text(artifact.filename).font(.caption.weight(.semibold)); Spacer(); Text(bytes(artifact.expectedBytes)).font(.caption.monospaced()) }
                        sourceLink(artifact.sourceURL)
                        Text("SHA256 \(artifact.expectedSHA256)").font(.caption2.monospaced()).textSelection(.enabled)
                    }.padding(11).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8))
                }
                if plan.artifacts.isEmpty { Text("No download artifacts in this plan.").font(.caption).foregroundStyle(Studio.muted) }
                detail("Source revision", plan.sourceRevision)
                detail("Installation path", plan.targetDirectory)
            }
            StructuredDetail(title: "Runtime pinned by this plan", value: plan.runtimeSnapshot)
            DisclosureGroup("Immutable plan identity") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Plan \(plan.id)\nSHA256 \(plan.planHash)")
                    if let existing = plan.existingInstallationHash { Text("Existing installation SHA256 \(existing)") }
                }.font(.caption2.monospaced()).textSelection(.enabled).padding(.top, 8)
            }.font(.caption).foregroundStyle(Studio.muted)
        }
    }
    private func requirements(_ plan: ProvisioningPlan) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Hardware and runtime requirements").font(.callout.weight(.semibold))
            detail("Platforms", plan.hardware.platforms.joined(separator: ", "))
            detail("Accelerators", plan.hardware.accelerators.joined(separator: ", "))
            detail("Packages", plan.hardware.requiredPackages.joined(separator: ", "))
            if let memory = plan.hardware.minimumMemoryGiB { detail("Minimum memory", String(format: "%.1f GiB", memory)) }
            if let disk = plan.hardware.estimatedDiskBytes { detail("Estimated disk", bytes(disk)) }
            ForEach(plan.hardware.notes, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted) }
        }
    }
    private func licensing(_ license: CapabilityLicense) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("License attribution").font(.callout.weight(.semibold))
            detail("Identifier", license.identifier)
            detail("Status", PlatformPresentation.label(license.status))
            detail("Code", license.code ?? "Not reported")
            detail("Weights", license.weights ?? "Not reported")
            ForEach(license.notes, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled) }
        }
    }
    private func jobSection(_ job: ProvisioningJob) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("Recorded job").font(.headline); Spacer(); PlatformStatus(status: job.status) }
            Text(PlatformPresentation.label(job.phase)).font(.callout.weight(.medium))
            Text(job.message).font(.callout).textSelection(.enabled)
            if job.active {
                ProgressView(value: job.progress)
                HStack { Text(job.progress, format: .percent.precision(.fractionLength(0))); Spacer(); if job.totalBytes > 0 { Text("\(bytes(job.downloadedBytes)) / \(bytes(job.totalBytes))") } }.font(.caption.monospaced()).foregroundStyle(Studio.muted)
            }
            Text("Updated \(PlatformPresentation.time(job.updatedAt)) · started \(PlatformPresentation.time(job.createdAt))").font(.caption2).foregroundStyle(Studio.muted)
            if let error = job.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
            if let result = job.result {
                Divider()
                Text("Recorded result: " + ProvisioningPresentation.resultTitle(result)).font(.callout.weight(.semibold)).foregroundStyle(result.smokeStatus == "passed" && result.installed ? Studio.accent : .orange)
                Text(result.message).font(.caption).textSelection(.enabled)
                detail("Installation", result.installationPath)
                detail("Smoke test", PlatformPresentation.label(result.smokeStatus))
                detail("Health receipt", result.healthReceiptID ?? "No successful receipt reported")
                Text("Execution readiness only. Project quality still requires reviewed examples and independent acceptance.").font(.caption).foregroundStyle(Studio.muted)
                StructuredDetail(title: "Recorded artifact hashes", value: result.artifactHashes)
            }
            if store.job?.id == job.id, job.status == "completed" {
                if store.loadingReceipt { HStack { ProgressView().controlSize(.small); Text("Reading the saved smoke receipt…").font(.caption) } }
                else if let error = store.receiptError { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                else if let receipt = store.receipt { receiptSection(receipt) }
            }
        }.panel()
    }
    private func receiptSection(_ receipt: ProvisioningHealth) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Matched smoke receipt").font(.callout.weight(.semibold))
            Text(receipt.inputDescription).font(.caption).textSelection(.enabled)
            HStack { fact("Measured execution", PlatformPresentation.duration(receipt.elapsedS)); fact("Observations", String(receipt.observationCount)); fact("Quality claim", receipt.qualityClaim) }
            Text("This receipt verifies the recorded adapter execution on that input. Current catalog readiness is refreshed separately; project accuracy is unmeasured.").font(.caption2).foregroundStyle(Studio.muted)
            DisclosureGroup("Input and execution identity") {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Input SHA256 \(receipt.inputSHA256)")
                    Text("Execution SHA256 \(receipt.executionIdentityHash)")
                    Text("Installation SHA256 \(receipt.installationHash)")
                }.font(.caption2.monospaced()).textSelection(.enabled).padding(.top, 7)
            }.font(.caption)
        }.padding(12).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 7))
    }
    private func bytes(_ count: Int64) -> String { ByteCountFormatter.string(fromByteCount: count, countStyle: .file) }
    private func fact(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) { Text(title).font(.caption2).foregroundStyle(Studio.muted); Text(value).font(.caption.weight(.medium)) }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func detail(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(title).frame(width: 120, alignment: .leading).foregroundStyle(Studio.muted); Text(value.isEmpty ? "Not specified" : value).textSelection(.enabled); Spacer(minLength: 0) }.font(.caption)
    }
    @ViewBuilder private func sourceLink(_ value: String) -> some View {
        if let url = URL(string: value), ["https", "http"].contains(url.scheme ?? "") { Link(value, destination: url).font(.caption).lineLimit(3) }
        else { Text(value).font(.caption).textSelection(.enabled) }
    }
}
