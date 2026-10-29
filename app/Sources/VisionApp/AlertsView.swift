import SwiftUI

struct AlertsView: View {
    @StateObject private var store: AlertWorkspace
    @NativeState<AlertTarget?> private var editingTarget: AlertTarget?
    @NativeState<AlertApproval?> private var approval: AlertApproval?
    init(projectID: String, client: EngineClient) { _store = StateObject(wrappedValue: AlertWorkspace(projectID: projectID, client: client)) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                header
                if let error = store.error { message(error, color: .orange, symbol: "exclamationmark.triangle") }
                if let notice = store.notice { message(notice, color: Studio.accent, symbol: "checkmark.circle") }
                if store.busy { HStack(spacing: 10) { ProgressView().controlSize(.small); Text("Updating alert configuration or delivery history…").font(.caption) } }
                if store.saved != nil {
                    configurationPanel
                    targetPanel
                    deliveryPanel
                } else if !store.busy {
                    EmptyCard(symbol: "bell.slash", title: "Alert configuration unavailable", detail: "Refresh to read this project's alert configuration from the local engine.").frame(height: 250).panel()
                }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }.task { await store.load() }
            .sheet(item: $editingTarget) { target in AlertTargetEditor(target: target, secretChange: store.secretChanges[target.id]) { target, secret in store.update(target, secret: secret) } }
            .sheet(item: $approval) { action in AlertApprovalSheet(action: action, store: store) }
    }
    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 6) {
                Eyebrow(text: "Approved destinations")
                Text("Route events. Inspect every delivery.").font(.title3.weight(.medium))
                Text("Only approved runs can create event alerts. Preview and evaluation never send alerts.").font(.callout).foregroundStyle(Studio.muted)
            }
            Spacer()
            Button("Refresh") {
                if store.isDirty { approval = .refresh } else { Task { await store.load() } }
            }.disabled(store.busy)
            Button("Review & save") { approval = .save }.buttonStyle(.borderedProminent).disabled(store.busy || !store.isDirty || store.validationMessage != nil)
        }
    }
    private var configurationPanel: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Toggle("Enable alerts for this project", isOn: $store.draft.enabled).toggleStyle(.switch)
                Spacer()
                StatusPill(text: store.isDirty ? "Unsaved draft" : "Revision \(store.draft.revision)", color: store.isDirty ? .orange : Studio.muted)
            }
            HStack(spacing: 12) {
                Text("Minimum interval").font(.callout)
                TextField("Seconds", value: $store.draft.minimumIntervalS, format: .number.grouping(.never)).textFieldStyle(.roundedBorder).frame(width: 90)
                Text("seconds between alerts per destination").font(.caption).foregroundStyle(Studio.muted)
                Spacer()
            }
            if let problem = store.validationMessage { Label(problem, systemImage: "info.circle").font(.caption).foregroundStyle(.orange) }
        }.panel().disabled(store.busy)
    }
    private var targetPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Eyebrow(text: "Destinations · \(store.draft.targets.count) / 10")
                Spacer()
                Menu {
                    ForEach(AlertKind.allCases) { kind in Button(kind.title) { editingTarget = .blank(kind: kind) } }
                } label: { Label("Add destination", systemImage: "plus") }.disabled(store.busy || store.draft.targets.count >= 10)
            }
            if store.draft.targets.isEmpty {
                Text("Add a webhook, email server, or MQTT broker. Alerts stay off until you review and approve the configuration.").font(.callout).foregroundStyle(Studio.muted).padding(.vertical, 16)
            }
            ForEach(store.draft.targets) { target in
                VStack(alignment: .leading, spacing: 12) {
                    HStack(alignment: .top, spacing: 12) {
                        Image(systemName: target.kind.symbol).font(.title3).foregroundStyle(Studio.accent).frame(width: 24)
                        VStack(alignment: .leading, spacing: 5) {
                            HStack { Text(target.name).font(.headline); StatusPill(text: target.enabled ? target.kind.title : "Disabled", color: target.enabled ? Studio.accent : Studio.muted) }
                            Text(target.destination).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
                            Text(store.credentialSummary(target)).font(.caption).foregroundStyle(Studio.muted)
                        }
                        Spacer()
                        Button("Edit") { editingTarget = target }
                        Button { store.remove(target) } label: { Image(systemName: "trash") }.help("Remove from draft; apply on review and save")
                    }
                    HStack {
                        if target.kind != .webhook { Text("Transport: \((target.tlsMode ?? .tls).title)").font(.caption).foregroundStyle(Studio.muted) }
                        Spacer()
                        Button("Send generated test…") { if let saved = store.saved?.targets.first(where: { $0.id == target.id }) { approval = .test(saved) } }
                            .disabled(store.isDirty || !target.enabled || store.saved?.targets.contains(where: { $0.id == target.id }) != true)
                    }
                }.padding(16).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 10)).disabled(store.busy)
            }
            if store.isDirty { Text("Save the draft before testing a destination. Removing a target takes effect only after Review & save.").font(.caption).foregroundStyle(Studio.muted) }
        }.panel()
    }
    private var deliveryPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Eyebrow(text: "Delivery history"); Spacer(); Button("Refresh receipts") { Task { await store.refreshHistory() } }.disabled(store.busy) }
            if store.deliveries.isEmpty {
                Text("No delivery attempts yet. Approved tests and event alerts appear here with their receipts or errors.").font(.callout).foregroundStyle(Studio.muted).padding(.vertical, 16)
            }
            ForEach(store.deliveries) { delivery in
                VStack(alignment: .leading, spacing: 9) {
                    HStack {
                        Text(delivery.targetName).font(.headline)
                        StatusPill(text: delivery.status.rawValue.capitalized, color: delivery.status == .sent ? Studio.accent : delivery.status == .failed ? .orange : Studio.muted)
                        Spacer()
                        Text("\(delivery.attempts) attempt\(delivery.attempts == 1 ? "" : "s")").font(.caption).foregroundStyle(Studio.muted)
                        if delivery.status.canRetry, let target = store.saved?.targets.first(where: { $0.id == delivery.targetID }) {
                            Button("Review retry…") { approval = .retry(delivery, target) }.disabled(store.busy || store.isDirty || !target.enabled)
                        }
                    }
                    Text("Event \(delivery.eventID) · \(delivery.createdAt)").font(.system(size: 11, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled)
                    if let sent = delivery.sentAt { Text("Sent: \(sent)").font(.caption).foregroundStyle(Studio.accent) }
                    if let error = delivery.error, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                    if delivery.status == .cancelled { Text("This delivery was cancelled by a configuration change. It will not be retried.").font(.caption).foregroundStyle(Studio.muted) }
                }.padding(14).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }.panel()
    }
    private func message(_ text: String, color: Color, symbol: String) -> some View {
        Label(text, systemImage: symbol).font(.callout).foregroundStyle(color).textSelection(.enabled).padding(14).frame(maxWidth: .infinity, alignment: .leading).background(color.opacity(0.08)).clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
