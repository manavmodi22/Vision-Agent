import SwiftUI

@main
struct VisionApp: App {
    @NSApplicationDelegateAdaptor(VisionAppDelegate.self) private var appDelegate
    @StateObject private var supervisor: EngineSupervisor
    @StateObject private var workspace: WorkspaceModel
    init() {
        _ = VisionBridge.runIfRequested()
        NativeSelfTests.runIfRequested()
        LiveReplayCLI.runIfRequested()
        let engine = EngineSupervisor()
        _supervisor = StateObject(wrappedValue: engine)
        let model = WorkspaceModel(supervisor: engine)
        _workspace = StateObject(wrappedValue: model)
        appDelegate.workspace = model
        NSApplication.shared.setActivationPolicy(.regular)
    }
    var body: some Scene {
        WindowGroup("VisionApp") {
            ContentView().environmentObject(workspace).environmentObject(supervisor)
                .frame(minWidth: 1080, minHeight: 740)
                .preferredColorScheme(.dark)
                .task { await workspace.start(); NSApp.activate(ignoringOtherApps: true) }
        }
        .defaultSize(width: 1380, height: 900)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New project") { NotificationCenter.default.post(name: .init("VisionNewProject"), object: nil) }.keyboardShortcut("n")
                Button("Import media…") { workspace.importMedia() }.keyboardShortcut("i").disabled(workspace.project == nil)
            }
        }
    }
}

@MainActor
final class VisionAppDelegate: NSObject, NSApplicationDelegate {
    weak var workspace: WorkspaceModel?
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let workspace else { return .terminateNow }
        Task {
            await workspace.liveCapture.stop()
            sender.reply(toApplicationShouldTerminate: await workspace.flushAnnotations())
        }
        return .terminateLater
    }
}
