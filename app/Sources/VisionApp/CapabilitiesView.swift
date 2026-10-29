import SwiftUI

struct CapabilitiesView: View {
    @EnvironmentObject var model: WorkspaceModel
    @StateObject private var store: CapabilityStore
    @NativeState<String> private var search = ""
    @NativeState<String> private var availability = "all"
    @NativeState<String> private var kind = "all"
    @NativeState<String?> private var selectedID: String?
    @NativeState<ProvisioningOption?> private var provisioning: ProvisioningOption?
    init(client: EngineClient, focusID: String? = nil) {
        _store = StateObject(wrappedValue: CapabilityStore(client: client)); _selectedID = .init(initialValue: focusID)
    }
    private var items: [Capability] {
        (store.catalog?.capabilities ?? []).filter {
            (availability == "all" || $0.availability == availability) && (kind == "all" || $0.kind == kind) && $0.matches(search)
        }.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
    private var selected: Capability? { items.first { $0.id == selectedID } ?? items.first }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Tools and models").font(.headline)
                    Text("Installation and execution readiness are checked separately.").font(.callout).foregroundStyle(Studio.muted)
                    if let catalog = store.catalog { Text("Catalog checked \(PlatformPresentation.time(catalog.generatedAt))").font(.caption2).foregroundStyle(Studio.muted) }
                }
                Spacer()
                if store.loading { ProgressView().controlSize(.small) }
                Button("Refresh") { Task { await store.refresh() } }.disabled(store.loading || !model.supervisor.connected)
            }
            if let error = store.error { Text(error).font(.callout).foregroundStyle(.orange).textSelection(.enabled) }
            HStack(spacing: 12) {
                TextField("Search capabilities or tasks", text: $search).textFieldStyle(.roundedBorder)
                Picker("Kind", selection: $kind) { Text("Tools & models").tag("all"); Text("Tools").tag("tool"); Text("Models").tag("model") }.frame(width: 170)
            }
            Picker("Availability", selection: $availability) {
                Text("All").tag("all"); Text("Installed").tag("installed")
                Text("Available to install").tag("available_to_install"); Text("Unsupported").tag("unsupported")
            }.pickerStyle(.segmented)
            if store.catalog == nil, store.loading {
                Spacer(); Text("Reading the engine's capability manifest…").foregroundStyle(Studio.muted); Spacer()
            } else if items.isEmpty {
                EmptyCard(symbol: "square.grid.2x2", title: "No matching capabilities", detail: store.catalog == nil ? "Connect to the engine and refresh the catalog." : "Change the search or availability filter.")
            } else {
                HStack(alignment: .top, spacing: 0) {
                    ScrollView {
                        LazyVStack(spacing: 5) {
                            ForEach(items) { capability in
                                Button { selectedID = capability.id } label: { row(capability) }.buttonStyle(.plain)
                            }
                        }.padding(.trailing, 14)
                    }.frame(minWidth: 270, idealWidth: 310, maxWidth: 360)
                    Divider()
                    if let selected {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 18) {
                                if let option = store.provisioningOptions.first(where: { $0.capabilityID == selected.id }) {
                                    HStack {
                                        Text(option.installed ? "Validate this installation with a bounded adapter smoke test." : "Review the exact download, license and validation plan before installing.").font(.caption).foregroundStyle(Studio.muted)
                                        Spacer()
                                        Button(option.action == "blocked" ? "Review requirements…" : option.installed ? "Review validation…" : "Review installation…") { provisioning = option }
                                            .buttonStyle(.borderedProminent).disabled(!model.supervisor.connected || store.loading)
                                    }.panel()
                                }
                                if let error = store.provisioningError { Text("Provisioning options unavailable: \(error)").font(.caption).foregroundStyle(.orange) }
                                CapabilityDetail(capability: selected)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 22).padding(.bottom, 24)
                        }.id(selected.id).frame(maxWidth: .infinity)
                    }
                }
            }
        }.padding(24)
            .task { if model.supervisor.connected { await store.refresh() } }
            .onChange(of: model.capabilityFocus) { _, focus in selectedID = focus; search = ""; availability = "all"; kind = "all" }
            .sheet(item: $provisioning, onDismiss: { Task { await store.refresh() } }) { option in
                ProvisioningSheet(client: model.client, option: option) { await store.refresh() }
            }
    }
    private func row(_ capability: Capability) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: capability.kind == "model" ? "cpu" : "wrench.and.screwdriver").foregroundStyle(Studio.muted)
                Text(capability.name).font(.callout.weight(.medium)).multilineTextAlignment(.leading)
                Spacer(minLength: 0)
            }
            HStack {
                Text(PlatformPresentation.label(capability.availability)).font(.caption2).foregroundStyle(Studio.muted)
                Spacer(minLength: 4)
                PlatformStatus(status: capability.verifiedCallable ? "ready" : capability.readiness.state == "ready" ? "blocked" : capability.readiness.state)
            }
            Text(capability.taskTypes.map(PlatformPresentation.label).joined(separator: " · ")).font(.caption2).foregroundStyle(Studio.muted).lineLimit(2)
        }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(selected?.id == capability.id ? Studio.raised : Studio.panel.opacity(0.6))
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct CapabilityDetail: View {
    let capability: Capability
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 8) {
                Text(capability.name).font(.title2.weight(.semibold))
                Text(capability.description).font(.callout).foregroundStyle(Studio.muted).textSelection(.enabled)
                Text(capability.id).font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled)
            }
            VStack(alignment: .leading, spacing: 9) {
                HStack { Text("Execution readiness").font(.callout.weight(.semibold)); Spacer(); PlatformStatus(status: capability.verifiedCallable ? "ready" : capability.readiness.state == "ready" ? "blocked" : capability.readiness.state) }
                Text(capability.readiness.reason).font(.callout).textSelection(.enabled)
                Text("Evidence: \(PlatformPresentation.label(capability.readiness.evidenceScope)) · checked \(PlatformPresentation.time(capability.readiness.checkedAt))").font(.caption2).foregroundStyle(Studio.muted)
                if let message = capability.validationEligibilityMessage { Text(message).font(.caption).foregroundStyle(capability.eligibleForValidation ? Studio.muted : .orange) }
            }.padding(14).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8))
            VStack(alignment: .leading, spacing: 9) {
                Text("Availability & requirements").font(.callout.weight(.semibold))
                detailRow("Availability", PlatformPresentation.label(capability.availability))
                detailRow("Version", capability.version ?? "Not reported")
                detailRow("Installation path", PlatformPresentation.label(capability.installMethod))
                detailRow("Platforms", capability.hardware.platforms.joined(separator: ", "))
                detailRow("Accelerators", capability.hardware.accelerators.joined(separator: ", "))
                if let memory = capability.hardware.minimumMemoryGiB { detailRow("Minimum memory", String(format: "%.1f GiB", memory)) }
                if let bytes = capability.hardware.estimatedDiskBytes { detailRow("Estimated disk", ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)) }
                if !capability.hardware.requiredPackages.isEmpty { detailRow("Packages", capability.hardware.requiredPackages.joined(separator: ", ")) }
                ForEach(capability.hardware.notes, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted) }
                if let instructions = capability.installInstructions { Text(instructions).font(.callout).textSelection(.enabled) }
                if !capability.dependencies.isEmpty { detailRow("Dependencies", capability.dependencies.joined(separator: ", ")) }
            }
            VStack(alignment: .leading, spacing: 9) {
                Text("License & provenance").font(.callout.weight(.semibold))
                detailRow("License", capability.license.identifier)
                detailRow("License status", PlatformPresentation.label(capability.license.status))
                if let code = capability.license.code { detailRow("Code", code) }
                if let weights = capability.license.weights { detailRow("Weights", weights) }
                ForEach(capability.license.notes, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted) }
                detailRow("Provenance scope", PlatformPresentation.label(capability.provenance.scope))
                if let revision = capability.provenance.revision { detailRow("Revision", revision) }
                ForEach(capability.provenance.sourceURLs, id: \.self) { source in
                    if let url = URL(string: source), let scheme = url.scheme, ["https", "http"].contains(scheme) { Link(source, destination: url).font(.caption).lineLimit(3) }
                    else { Text(source).font(.caption).textSelection(.enabled) }
                }
                ForEach(capability.provenance.notes, id: \.self) { Text($0).font(.caption).foregroundStyle(Studio.muted) }
                if !capability.provenance.hashes.isEmpty { StructuredDetail(title: "Recorded hashes", value: capability.provenance.hashes) }
            }
            if !capability.sideEffects.isEmpty {
                VStack(alignment: .leading, spacing: 7) { Text("Side effects").font(.callout.weight(.semibold)); ForEach(capability.sideEffects, id: \.self) { Text(PlatformPresentation.label($0)).font(.caption) } }
            }
            VStack(alignment: .leading, spacing: 10) {
                Text("Readiness evidence").font(.callout.weight(.semibold))
                if capability.readiness.evidence.isEmpty { Text("No evidence recorded.").font(.caption).foregroundStyle(Studio.muted) }
                ForEach(Array(capability.readiness.evidence.enumerated()), id: \.offset) { _, evidence in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack { Text(evidence.subject).font(.caption.weight(.medium)); Spacer(); PlatformStatus(status: evidence.outcome) }
                        Text(evidence.detail).font(.caption).textSelection(.enabled)
                        Text("\(PlatformPresentation.label(evidence.kind)) · \(PlatformPresentation.time(evidence.observedAt))").font(.caption2).foregroundStyle(Studio.muted)
                        if !evidence.metadata.isEmpty { StructuredDetail(title: "Evidence metadata", value: evidence.metadata) }
                    }.padding(10).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 6))
                }
            }
            StructuredDetail(title: "Input schema", value: capability.inputSchema)
            StructuredDetail(title: "Output schema", value: capability.outputSchema)
        }
    }
    private func detailRow(_ title: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(title).foregroundStyle(Studio.muted).frame(width: 115, alignment: .leading); Text(value.isEmpty ? "Not specified" : value).textSelection(.enabled); Spacer(minLength: 0) }.font(.caption)
    }
}
