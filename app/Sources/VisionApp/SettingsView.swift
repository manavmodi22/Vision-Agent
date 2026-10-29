import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: WorkspaceModel
    @EnvironmentObject var supervisor: EngineSupervisor
    @AppStorage("vision.experimentalInvestigations") private var experimentalInvestigations = false
    var server: [String: JSONValue] { model.health?.object["model_server"]?.object ?? [:] }
    var reachable: Bool { server["reachable"] == .bool(true) }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(alignment: .top, spacing: 20) {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack { Eyebrow(text: "Local model server"); Spacer(); StatusPill(text: reachable ? "Reachable" : "Offline", color: reachable ? Studio.accent : .orange) }
                        Text("Bring your own local models.").font(.title3.weight(.medium))
                        Text("LM Studio, Ollama, or another OpenAI-compatible server can provide planning and visual judgement. Configure exact model names loaded by your server.").font(.callout).foregroundStyle(Studio.muted)
                        VStack(alignment: .leading, spacing: 8) { Text("API base URL").font(.caption); TextField("http://localhost:1234/v1", text: $model.settings.modelUrl).textFieldStyle(.roundedBorder) }
                        VStack(alignment: .leading, spacing: 8) { Text("Planner model").font(.caption); TextField("Loaded planner model ID", text: $model.settings.plannerModel).textFieldStyle(.roundedBorder) }
                        VStack(alignment: .leading, spacing: 8) { Text("Vision-language API base URL").font(.caption); TextField("http://127.0.0.1:1235/v1", text: $model.settings.vlmUrl).textFieldStyle(.roundedBorder) }
                        VStack(alignment: .leading, spacing: 8) { Text("Vision-language model").font(.caption); TextField("Loaded VLM ID", text: $model.settings.vlmModel).textFieldStyle(.roundedBorder) }
                        DisclosureGroup("Advanced compatibility") {
                            VStack(alignment: .leading, spacing: 8) {
                                Picker("Agent decision format", selection: $model.settings.investigationTransport) {
                                    Text("JSON schema").tag("structured_json")
                                    Text("Function call").tag("decision_function")
                                    if !["structured_json", "decision_function"].contains(model.settings.investigationTransport) {
                                        Text("Current format: \(model.settings.investigationTransport)").tag(model.settings.investigationTransport)
                                    }
                                }.pickerStyle(.menu)
                                Text("Use the format your local model supports for investigations. Function call submits one typed agent decision; the engine validates it before executing the selected action.").font(.caption).foregroundStyle(Studio.muted)
                            }.padding(.top, 8)
                        }.font(.callout)
                        if let error = server["error"]?.string, !error.isEmpty { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
                        HStack { Button("Check connection") { model.perform("Checking model server") { try await model.refresh() } }; Spacer(); Button("Save settings") { model.saveSettings() }.buttonStyle(.borderedProminent) }.disabled(model.busy)
                    }.frame(maxWidth: .infinity).panel()
                    VStack(alignment: .leading, spacing: 18) {
                        Eyebrow(text: "Agent runtime")
                        Toggle("Experimental agent", isOn: $experimentalInvestigations)
                        Text("Applies to new app sessions. The agent chooses bounded vision experiments and can construct a draft. Existing sessions keep their runtime. Draft review handoff is not yet available.").font(.caption).foregroundStyle(Studio.muted)
                        Divider()
                        Eyebrow(text: "Model policy")
                        Toggle("Allow AGPL models", isOn: $model.settings.allowAgpl).disabled(true)
                        Text("AGPL adapters are not installed in this build.").font(.caption).foregroundStyle(Studio.muted)
                        Text("Permissive models are the default. Model licences and local availability are checked by the compiler. Review each model's terms before distribution.").font(.callout).foregroundStyle(Studio.muted)
                        Divider()
                        Eyebrow(text: "Device access")
                        Label("Apple Vision OCR and barcodes", systemImage: "checkmark.circle").font(.callout).foregroundStyle(Studio.accent)
                        Text("Start a camera, or choose a display/window, in Run. macOS asks for access only when you explicitly select capture. Recorded-video replay needs no capture permission.").font(.caption).foregroundStyle(Studio.muted)
                        Divider()
                        Eyebrow(text: "Storage")
                        Text(supervisor.dataRoot.path).font(.system(size: 10, design: .monospaced)).textSelection(.enabled)
                        Button("Open data folder") { NSWorkspace.shared.open(supervisor.dataRoot) }.font(.caption)
                    }.frame(width: 290).panel()
                }
                VStack(alignment: .leading, spacing: 16) {
                    Eyebrow(text: "Vision model inventory")
                    ForEach(Array(model.models.enumerated()), id: \.offset) { _, item in
                        let fields = item.object
                        HStack(alignment: .top, spacing: 16) {
                            Image(systemName: "cpu").foregroundStyle(Studio.accent).padding(.top, 3)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(fields["id"]?.string ?? fields["name"]?.string ?? "Model").font(.headline)
                                Text(fields.keys.sorted().filter { $0 != "id" && $0 != "name" }.map { "\($0): \(fields[$0]?.display ?? "")" }.joined(separator: " · ")).font(.caption).foregroundStyle(Studio.muted).textSelection(.enabled)
                            }; Spacer()
                        }.padding(12).background(Studio.background).clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                }.panel()
                VStack(alignment: .leading, spacing: 14) {
                    HStack { Eyebrow(text: "Engine diagnostics"); Spacer(); Text(supervisor.status).font(.caption).foregroundStyle(Studio.muted) }
                    Text("Socket: \(supervisor.socketPath)").font(.system(size: 10, design: .monospaced)).textSelection(.enabled)
                    ScrollView { Text(supervisor.logs.isEmpty ? "No engine logs in this session." : supervisor.logs).font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }.frame(height: 150)
                }.panel()
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }
    }
}
