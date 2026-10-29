import SwiftUI

struct AlertApprovalSheet: View {
    @Environment(\.dismiss) private var dismiss
    let action: AlertApproval
    @ObservedObject var store: AlertWorkspace
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            switch action {
            case .save: saveReview
            case .test(let target):
                Text("Send a generated test").font(.title2.weight(.semibold))
                destination(target)
                Text("This sends a generated VisionApp test message to the saved destination above. It does not include project images or event evidence.").font(.callout).foregroundStyle(Studio.muted)
                buttons("Send test message") { Task { await store.testApproved(target) } }
            case .retry(let delivery, let target):
                Text("Retry this delivery").font(.title2.weight(.semibold))
                destination(target)
                Text("Event: \(delivery.eventID)").font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
                Text("Retry sends the stored event payload to the current approved destination. A failed delivery can still have reached the recipient; retrying may produce a duplicate.").font(.callout).foregroundStyle(Studio.muted)
                if let error = delivery.error { Text(error).font(.caption).foregroundStyle(.orange) }
                buttons("Approve retry") { Task { await store.retryApproved(delivery, target: target) } }
            case .refresh:
                Text("Discard this alert draft?").font(.title2.weight(.semibold))
                Text("Refresh reloads the saved configuration. Unsaved destination edits and staged credential changes will be removed from this screen.").font(.callout).foregroundStyle(Studio.muted)
                buttons("Discard draft & refresh") { Task { await store.load() } }
            }
        }.padding(28).frame(width: 580)
    }
    private var saveReview: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Review alert changes").font(.title2.weight(.semibold))
            HStack { StatusPill(text: store.draft.enabled ? "Project alerts will be enabled" : "Project alerts will be disabled", color: store.draft.enabled ? Studio.accent : Studio.muted); Spacer() }
            Text("Minimum interval: \(store.draft.minimumIntervalS.formatted()) seconds. Configuration revision: \(store.draft.revision).").font(.caption).foregroundStyle(Studio.muted)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(store.draft.targets) { target in
                        VStack(alignment: .leading, spacing: 7) {
                            destination(target)
                            Text(store.credentialSummary(target)).font(.caption).foregroundStyle(Studio.muted)
                        }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    ForEach(store.saved?.targets.filter { saved in !store.draft.targets.contains(where: { $0.id == saved.id }) } ?? []) { removed in
                        VStack(alignment: .leading, spacing: 5) { Text("Remove: \(removed.name)").font(.headline).foregroundStyle(.orange); Text(removed.destination).font(.caption.monospaced()).textSelection(.enabled) }
                    }
                }
            }.frame(maxHeight: 360)
            Text("Saving approves these destinations for future alerts from approved runs. Saving itself does not send a test message.").font(.callout).foregroundStyle(Studio.muted)
            buttons("Approve & save configuration") { Task { await store.saveApproved() } }
        }
    }
    private func destination(_ target: AlertTarget) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("\(target.name) · \(target.kind.title)\(target.enabled ? "" : " · Disabled")").font(.headline)
            Text(target.destination).font(.system(size: 12, design: .monospaced)).textSelection(.enabled)
            if let sender = target.fromAddress, !sender.isEmpty { Text("From: \(sender)").font(.caption) }
            if let tls = target.tlsMode { Text("Security: \(tls.title)").font(.caption).foregroundStyle(Studio.muted) }
        }
    }
    private func buttons(_ title: String, action: @escaping () -> Void) -> some View {
        HStack { Button("Cancel") { dismiss() }; Spacer(); Button(title) { dismiss(); action() }.buttonStyle(.borderedProminent) }
    }
}
