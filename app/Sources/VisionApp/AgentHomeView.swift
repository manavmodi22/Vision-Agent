import SwiftUI
import UniformTypeIdentifiers

struct SampleCatalogItem: Decodable, Identifiable {
    let id: String
    let name: String
    let description: String
    let origin: String
    let license: String
    let available: Bool
}

struct AgentHomeView: View {
    @EnvironmentObject var model: WorkspaceModel
    @EnvironmentObject var supervisor: EngineSupervisor
    @AppStorage("vision.experimentalInvestigations") private var experimentalInvestigations = false
    @NativeState<String> private var goal = ""
    @NativeState<[URL]> private var media = []
    @NativeState<[SampleCatalogItem]> private var samples = []
    @NativeState<String?> private var sampleID: String?
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("What are you building?").font(.system(size: 30, weight: .medium))
                Text("Describe the vision app you need. Your agent builds it and tests it on your examples.").font(.callout).foregroundStyle(Studio.muted)
                if experimentalInvestigations { Text("Experimental agent · drafts require review and explicit import").font(.caption).foregroundStyle(.orange) }
                VStack(alignment: .leading, spacing: 16) {
                    ZStack(alignment: .topLeading) {
                        if goal.isEmpty { Text("Describe what to detect and what should happen…").font(.system(size: 16)).foregroundStyle(Studio.muted).padding(16).allowsHitTesting(false) }
                        TextEditor(text: $goal).font(.system(size: 16)).scrollContentBackground(.hidden).padding(10).frame(height: 150)
                    }
                    if !media.isEmpty {
                        ForEach(media, id: \.path) { url in
                            HStack { Image(systemName: "paperclip"); Text(url.lastPathComponent).lineLimit(1); Spacer(); Button { media.removeAll { $0 == url } } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }.font(.caption).foregroundStyle(Studio.muted).padding(.horizontal, 16)
                        }
                    }
                    if let sample = samples.first(where: { $0.id == sampleID }) {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack { Label(sample.name, systemImage: "film"); Spacer(); Button { sampleID = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain) }
                            Text("\(sample.origin) · \(sample.license)").font(.caption2).foregroundStyle(Studio.muted)
                        }.font(.caption).padding(.horizontal, 16)
                    }
                    HStack {
                        Button { chooseMedia() } label: { Label("Use my data", systemImage: "paperclip") }
                        if let sample = samples.first(where: \.available) {
                            Button("Try warehouse footage") {
                                sampleID = sample.id; media = []
                                if goal.isEmpty { goal = "Count people in this warehouse footage and show bounding boxes." }
                            }
                        }
                        Spacer()
                        Button("Build my app") { model.createAndBuild(goal: goal, paths: media.map(\.path), sampleID: sampleID) }
                            .buttonStyle(.borderedProminent).disabled(model.busy || goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }.padding(16)
                }.background(Studio.panel).clipShape(RoundedRectangle(cornerRadius: 12)).overlay(RoundedRectangle(cornerRadius: 12).stroke(.white.opacity(0.1)))
                VStack(alignment: .leading, spacing: 10) {
                    Text("Start with an outcome").font(.caption).foregroundStyle(Studio.muted)
                    ForEach(["Count people in warehouse images.", "Find damaged cartons and save a crop for review.", "Read package labels and show their codes."], id: \.self) { example in
                        Button { goal = example } label: { HStack { Text(example); Spacer(); Image(systemName: "arrow.up.left") }.font(.callout).foregroundStyle(Studio.muted) }.buttonStyle(.plain)
                    }
                }
                if !model.projects.isEmpty {
                    Divider().padding(.vertical, 10)
                    Text("Continue an app").font(.headline)
                    ForEach(model.projects.prefix(6)) { project in
                        Button { model.select(project.id) } label: {
                            HStack { Image(systemName: "square.stack").foregroundStyle(Studio.accent); Text(project.name).font(.callout); Spacer(); Text(project.status.capitalized).font(.caption).foregroundStyle(Studio.muted); Image(systemName: "chevron.right").font(.caption).foregroundStyle(Studio.muted) }
                        }.buttonStyle(.plain).padding(.vertical, 5)
                    }
                }
            }.frame(maxWidth: 740, alignment: .leading).padding(.horizontal, 36).padding(.top, 44).padding(.bottom, 40).frame(maxWidth: .infinity)
        }.task(id: supervisor.connected) {
            guard supervisor.connected else { return }
            samples = (try? await model.client.request("GET", "/samples/catalog")) ?? []
        }
    }
    private func chooseMedia() {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.image, .movie, .folder]
        panel.canChooseDirectories = true; panel.allowsMultipleSelection = true
        panel.message = "Choose representative photos, video, or an image folder for your goal."
        if panel.runModal() == .OK { media = panel.urls; sampleID = nil }
    }
}
