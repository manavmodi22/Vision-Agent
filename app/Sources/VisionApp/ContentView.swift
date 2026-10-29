import SwiftUI

struct ContentView: View {
    @EnvironmentObject var model: WorkspaceModel
    @EnvironmentObject var supervisor: EngineSupervisor
    @NativeState<Bool> private var newProject = false
    @NativeState<String> private var projectName = ""
    @NativeState<String> private var projectGoal = ""
    @NativeState<Bool> private var showTools = false
    private let tools: [(String, String, String)] = [
        ("Dataset", "Annotations", "rectangle.grid.2x2"), ("Workflow", "Workflow", "point.3.connected.trianglepath.dotted"),
        ("Zones", "Zones", "square.dashed"), ("Evaluate", "Evaluation", "checkmark.shield"),
        ("Alerts", "Alerts", "bell.badge"), ("Events", "Evidence", "clock.arrow.circlepath"), ("Review", "Review queue", "tray.full")]
    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 220)
            Divider().overlay(.white.opacity(0.03))
            VStack(spacing: 0) {
                topbar
                if let error = model.error { banner(error, color: .orange, icon: "exclamationmark.triangle") }
                if let notice = model.notice { banner(notice, color: Studio.accent, icon: "info.circle") }
                if model.busy {
                    HStack(spacing: 10) { ProgressView().controlSize(.small); Text(model.activity).font(.caption); Spacer() }
                        .padding(.horizontal, 28).padding(.vertical, 9).background(Studio.accent.opacity(0.08))
                }
                Group {
                    if model.section == "Settings" { SettingsView() }
                    else if model.section == "Capabilities" { CapabilitiesView(client: model.client, focusID: model.capabilityFocus) }
                    else if model.project == nil { AgentHomeView() }
                    else {
                        switch model.section {
                        case "Dataset": if let id = model.selectedID { DatasetStudio(store: model.datasetWorkspace(for: id)).id(id) }
                        case "Workflow": WorkflowDetailsView()
                        case "Zones": ZonesView()
                        case "Evaluate": EvaluateView()
                        case "Run": RunView()
                        case "Alerts": if let id = model.selectedID { AlertsView(projectID: id, client: model.client).id(id) }
                        case "Events": EventsView()
                        case "Review": ReviewView()
                        default: if let id = model.selectedID { BuildView(store: model.agentWorkspace(for: id), dataset: model.datasetWorkspace(for: id)).id(id) }
                        }
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }.background(Studio.background).tint(Studio.accent)
            .sheet(isPresented: $newProject) { newProjectSheet }
            .onReceive(NotificationCenter.default.publisher(for: .init("VisionNewProject"))) { _ in newProject = true }
            .onChange(of: model.prompt) { _, _ in model.savePromptDraft() }
            .onChange(of: model.section) { _, section in if tools.contains(where: { $0.0 == section }) { showTools = true } }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) { Image(systemName: "viewfinder").font(.system(size: 23, weight: .medium)).foregroundStyle(Studio.accent); Text("VisionApp").font(.system(size: 18, weight: .semibold)) }.padding(.top, 30).padding(.bottom, 28).padding(.horizontal, 20)
            Button { model.select(nil) } label: { Label("Build a new app", systemImage: "plus").font(.callout).frame(maxWidth: .infinity, alignment: .leading) }.buttonStyle(.plain).padding(14).background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 8)).padding(.horizontal, 12).disabled(model.busy)
            HStack { Text("Your apps").font(.caption).foregroundStyle(Studio.muted); Spacer(); Button { newProject = true } label: { Image(systemName: "folder.badge.plus") }.buttonStyle(.plain).help("Create a named project") }.padding(.horizontal, 20).padding(.top, 24).padding(.bottom, 8)
            ScrollView {
                VStack(spacing: 4) {
                    ForEach(model.projects) { project in
                        Button { model.select(project.id) } label: {
                            HStack(alignment: .top, spacing: 9) {
                                Image(systemName: project.synthetic ? "testtube.2" : "square.stack").padding(.top, 3)
                                VStack(alignment: .leading, spacing: 4) { Text(project.name).font(.system(size: 12, weight: .medium)).lineLimit(2); Text(project.fixture == true ? "Synthetic walkthrough" : project.status.capitalized).font(.system(size: 10)).foregroundStyle(Studio.muted) }; Spacer(minLength: 0)
                            }.foregroundStyle(model.selectedID == project.id ? Studio.accent : .white.opacity(0.8)).padding(11).frame(maxWidth: .infinity, alignment: .leading)
                                .background(model.selectedID == project.id ? Studio.accent.opacity(0.09) : .clear).clipShape(RoundedRectangle(cornerRadius: 8))
                        }.buttonStyle(.plain).disabled(model.busy)
                    }
                }.padding(.horizontal, 10)
            }.frame(maxHeight: 260)
            Divider().padding(.horizontal, 20).padding(.vertical, 16)
            navigation("Agent", title: "Agent", symbol: "bubble.left.and.bubble.right")
            navigation("Run", title: "Application", symbol: "play.rectangle")
            DisclosureGroup("Tools", isExpanded: $showTools) {
                VStack(spacing: 2) { ForEach(tools, id: \.0) { section, title, symbol in navigation(section, title: title, symbol: symbol) } }.padding(.top, 8)
            }.font(.caption).foregroundStyle(Studio.muted).padding(.horizontal, 16).padding(.top, 18)
            Spacer(minLength: 10)
            navigation("Capabilities", title: "Capabilities", symbol: "square.grid.3x3", requiresProject: false)
            Button { model.section = "Settings" } label: { Label("Settings & models", systemImage: "slider.horizontal.3").font(.system(size: 12)).foregroundStyle(Studio.muted) }.buttonStyle(.plain).padding(20)
            HStack(spacing: 7) { Circle().fill(supervisor.connected ? Studio.accent : .orange).frame(width: 5, height: 5); Text(supervisor.status).font(.system(size: 10)).lineLimit(2) }.foregroundStyle(Studio.muted).padding(.horizontal, 20).padding(.bottom, 22)
        }.background(Color.black.opacity(0.12))
    }
    private func navigation(_ section: String, title: String, symbol: String, requiresProject: Bool = true) -> some View {
        Button { model.section = section } label: {
            HStack(spacing: 11) { Image(systemName: symbol).frame(width: 18); Text(title).font(.system(size: 13)); Spacer() }
                .padding(.horizontal, 14).padding(.vertical, 10).foregroundStyle(model.section == section ? .white : Studio.muted)
                .background(model.section == section ? Studio.raised : .clear).clipShape(RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).padding(.horizontal, 6).disabled(requiresProject && model.project == nil)
    }
    private var topbar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 5) {
                Text(model.project?.name ?? "VisionApp Agent").font(.caption).foregroundStyle(Studio.muted)
                Text(model.section == "Settings" ? "Settings & models" : model.section == "Capabilities" ? "Capabilities" : model.project == nil ? "Build your app" : model.section == "Dataset" ? "Annotations" : model.section == "Run" ? "Application" : model.section).font(.system(size: 25, weight: .medium))
            }
            Spacer()
            if model.project?.synthetic == true { StatusPill(text: model.project?.fixture == true ? "Synthetic fixtures" : "Synthetic imagery", color: .orange) }
            Text("On this Mac").font(.caption).foregroundStyle(Studio.muted)
        }.padding(.horizontal, 28).padding(.vertical, 20)
    }
    private func banner(_ text: String, color: Color, icon: String) -> some View {
        HStack(alignment: .top, spacing: 10) { Image(systemName: icon); Text(text).font(.callout).textSelection(.enabled); Spacer(); Button { model.error = nil; model.notice = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }
            .foregroundStyle(color).padding(13).background(color.opacity(0.08)).padding(.horizontal, 28).padding(.bottom, 10)
    }
    private var newProjectSheet: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Create a named app").font(.title2.weight(.semibold))
            TextField("App name", text: $projectName).textFieldStyle(.roundedBorder)
            Text("What should it do?").font(.callout)
            TextEditor(text: $projectGoal).font(.callout).frame(height: 100)
            HStack { Button("Cancel") { newProject = false }; Spacer(); Button("Create app") { newProject = false; model.create(name: projectName, goal: projectGoal) }.buttonStyle(.borderedProminent).disabled(projectName.trimmingCharacters(in: .whitespaces).isEmpty) }
        }.padding(28).frame(width: 470)
    }
}
