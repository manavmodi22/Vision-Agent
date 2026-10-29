import SwiftUI

struct AlertTargetEditor: View {
    @Environment(\.dismiss) private var dismiss
    @NativeState<AlertTarget> private var target: AlertTarget
    @NativeState<String> private var secret: String
    @NativeState<Bool> private var removeSecret: Bool
    let original: AlertTarget
    let onSave: (AlertTarget, JSONValue?) -> Void
    init(target: AlertTarget, secretChange: JSONValue?, onSave: @escaping (AlertTarget, JSONValue?) -> Void) {
        original = target; self.onSave = onSave
        _target = NativeState(initialValue: target)
        _secret = NativeState(initialValue: secretChange?.string ?? "")
        _removeSecret = NativeState(initialValue: secretChange == .null)
    }
    private func optionalString(_ keyPath: WritableKeyPath<AlertTarget, String?>) -> Binding<String> {
        Binding(get: { target[keyPath: keyPath] ?? "" }, set: { target[keyPath: keyPath] = $0.isEmpty ? nil : $0 })
    }
    private var recipients: Binding<String> {
        Binding(get: { (target.recipients ?? []).joined(separator: ", ") }, set: {
            target.recipients = $0.components(separatedBy: CharacterSet(charactersIn: ",;\n")).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Image(systemName: target.kind.symbol).foregroundStyle(Studio.accent); Text("Alert target").font(.title2.weight(.semibold)); Spacer(); Toggle("Enabled", isOn: $target.enabled).toggleStyle(.switch).controlSize(.small) }
            Text("Changes remain a draft until you review and save the project alert configuration.").font(.callout).foregroundStyle(Studio.muted)
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    labelled("Name") { TextField("Operations alerts", text: $target.name).textFieldStyle(.roundedBorder) }
                    Picker("Transport", selection: Binding(get: { target.kind }, set: { kind in
                        target.setTransport(kind); secret = ""; removeSecret = original.hasSecret
                    })) { ForEach(AlertKind.allCases) { Text($0.title).tag($0) } }.pickerStyle(.segmented)
                    if target.kind == .webhook { webhookFields } else { serverFields }
                    Divider()
                    credentialFields
                    if let problem = target.validationMessage { Label(problem, systemImage: "info.circle").font(.caption).foregroundStyle(.orange) }
                }.padding(.vertical, 2)
            }.frame(maxHeight: 510)
            HStack {
                Button("Cancel") { secret = ""; dismiss() }
                Spacer()
                Button("Keep in draft") {
                    let change: JSONValue? = removeSecret ? .null : secret.isEmpty ? nil : .string(secret)
                    onSave(target, change); secret = ""; dismiss()
                }.buttonStyle(.borderedProminent).disabled(target.validationMessage != nil)
            }
        }.padding(28).frame(width: 540)
    }
    private var webhookFields: some View {
        VStack(alignment: .leading, spacing: 8) {
            labelled("Webhook URL") { TextField("https://ops.example.com/vision-alerts", text: optionalString(\.url)).textFieldStyle(.roundedBorder) }
            Text("HTTPS is required for external destinations. Plain HTTP is accepted only on loopback for local testing.").font(.caption).foregroundStyle(Studio.muted)
        }
    }
    private var serverFields: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 16) {
                labelled("Server hostname") { TextField("Server hostname", text: optionalString(\.host)).textFieldStyle(.roundedBorder) }
                labelled("Port") { TextField("Port", value: Binding(get: { target.port ?? 0 }, set: { target.port = $0 }), format: .number.grouping(.never)).textFieldStyle(.roundedBorder).frame(width: 85) }
            }
            Picker("Transport security", selection: Binding(get: { target.tlsMode ?? .tls }, set: { target.tlsMode = $0 })) {
                Text("TLS").tag(AlertTLS.tls)
                if target.kind == .smtp { Text("STARTTLS").tag(AlertTLS.starttls) }
                Text("No TLS · loopback only").tag(AlertTLS.none)
            }
            if target.kind == .smtp {
                labelled("From address") { TextField("vision@example.com", text: optionalString(\.fromAddress)).textFieldStyle(.roundedBorder) }
                labelled("Recipient addresses · separate with commas") { TextField("operations@example.com", text: recipients).textFieldStyle(.roundedBorder) }
            } else {
                labelled("MQTT topic") { TextField("visionapp/events", text: optionalString(\.topic)).textFieldStyle(.roundedBorder) }
            }
            labelled("Username · optional") { TextField("Username", text: optionalString(\.username)).textFieldStyle(.roundedBorder) }
        }
    }
    private var credentialFields: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack { Eyebrow(text: target.kind == .webhook ? "Bearer token" : "Password"); Spacer(); if original.hasSecret { StatusPill(text: "Credential stored", color: Studio.muted) } }
            SecureField(original.hasSecret ? "Leave blank to preserve the stored credential" : "Optional credential", text: $secret).textFieldStyle(.roundedBorder).disabled(removeSecret)
            if original.hasSecret { Toggle("Remove stored credential when configuration is saved", isOn: $removeSecret).font(.caption) }
            Text("Saved credentials are never returned to this screen. A blank field preserves an existing credential.").font(.caption).foregroundStyle(Studio.muted)
        }
    }
    private func labelled<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 7) { Text(title).font(.caption).foregroundStyle(Studio.muted); content() }
    }
}
