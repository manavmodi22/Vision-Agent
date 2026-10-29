import Foundation
import AppKit

@MainActor
final class EngineSupervisor: ObservableObject {
    @Published var status = "Starting engine"
    @Published var logs = ""
    @Published private(set) var connected = false
    let repoRoot: URL
    let dataRoot: URL
    let socketPath: String
    private let bundledPython: URL?
    private let packageParent: URL
    private let expectedBuild: String
    private var process: Process?
    private var restartCount = 0
    private var stopping = false
    private var terminationObserver: NSObjectProtocol?

    init() {
        let env = ProcessInfo.processInfo.environment
        let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let packagedPython = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources/PythonRuntime/bin/python3.12")
        bundledPython = FileManager.default.isExecutableFile(atPath: packagedPython.path) ? packagedPython : nil
        let rootPointer = Bundle.main.resourceURL?.appendingPathComponent("repo-root.txt")
        let configuredPath = rootPointer.flatMap { try? String(contentsOf: $0, encoding: .utf8) }?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let resourceRoot = configuredPath.flatMap { $0.hasPrefix("/") ? URL(fileURLWithPath: $0) : nil }
        let current = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let candidates = [env["VISION_REPO_ROOT"].map { URL(fileURLWithPath: $0) }, resourceRoot, current,
                          executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()].compactMap { $0 }
        if bundledPython != nil, let resources = Bundle.main.resourceURL {
            repoRoot = resources.appendingPathComponent("engine")
        } else {
            repoRoot = candidates.first { FileManager.default.fileExists(atPath: $0.appendingPathComponent("pyproject.toml").path) } ?? current
        }
        dataRoot = env["VISION_DATA_DIR"].map { URL(fileURLWithPath: $0) } ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/VisionApp")
        packageParent = bundledPython?.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("lib/python3.12/site-packages") ?? repoRoot
        expectedBuild = (try? EngineBuildIdentity.sourceHash(packageParent)) ?? "missing"
        let workspaceKey = EngineBuildIdentity.shortHash(dataRoot.resolvingSymlinksInPath().path)
        socketPath = env["VISION_SOCKET"] ?? "/tmp/visionapp-\(getuid())/\(workspaceKey)-\(expectedBuild.prefix(12)).sock"
        terminationObserver = NotificationCenter.default.addObserver(forName: NSApplication.willTerminateNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.stop() }
        }
    }
    var client: EngineClient { EngineClient(socketPath: socketPath) }
    private var python: URL { bundledPython ?? repoRoot.appendingPathComponent(".venv/bin/python") }
    private func compatible(_ health: SupervisorHealth) -> Bool {
        health.runtime?.matches(data: dataRoot, executable: python, packages: packageParent, build: expectedBuild) == true
    }
    func validateConnection() async throws {
        let health: SupervisorHealth = try await client.request("GET", "/health")
        connected = compatible(health)
        guard connected else {
            status = "Incompatible engine — see Settings"
            throw EngineError.protocolError("The socket serves a different engine build or workspace.")
        }
        status = "Engine connected"
    }
    func start() async {
        connected = false
        if let health: SupervisorHealth = try? await client.request("GET", "/health") {
            connected = compatible(health)
            status = compatible(health) ? "Engine connected" : "Incompatible engine — see Settings"
            if !compatible(health) { logs += "The socket serves a different build, interpreter or workspace. Close that engine or select a separate VISION_SOCKET.\n" }
            return
        }
        launch()
        for _ in 0..<150 {
            try? await Task.sleep(for: .milliseconds(300))
            guard !stopping else { return }
            if let health: SupervisorHealth = try? await client.request("GET", "/health"), compatible(health) {
                connected = true
                status = "Engine connected"
                return
            }
        }
        status = "Engine unavailable — see Settings"
    }
    private func launch() {
        guard !stopping else { return }
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            status = "Engine environment missing"
            logs += "Run scripts/bootstrap.sh in \(repoRoot.path) to install the engine.\n"
            return
        }
        let child = Process()
        child.executableURL = python
        child.arguments = ["-B", "-m", "engine.api", "--socket", socketPath, "--data-dir", dataRoot.path,
                           "--parent-pid", String(getpid())]
        child.currentDirectoryURL = repoRoot
        var environment = ProcessInfo.processInfo.environment
        environment.removeValue(forKey: "PYTHONHOME")
        environment.removeValue(forKey: "PYTHONPATH")
        environment.removeValue(forKey: "VIRTUAL_ENV")
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["VISION_APP_BINARY"] = Bundle.main.executableURL?.path ?? CommandLine.arguments[0]
        environment["PYTHONUNBUFFERED"] = "1"
        environment["VISION_DATA_DIR"] = dataRoot.path
        environment["VISION_SOCKET"] = socketPath
        child.environment = environment
        let pipe = Pipe()
        child.standardOutput = pipe
        child.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in self?.logs = String(((self?.logs ?? "") + text).suffix(24000)) }
        }
        child.terminationHandler = { [weak self] process in
            Task { @MainActor in
                guard let self, !self.stopping else { return }
                self.status = "Engine exited (\(process.terminationStatus))"
                self.connected = false
                if self.restartCount < 3 {
                    self.restartCount += 1
                    self.logs += "Restarting engine (\(self.restartCount)/3).\n"
                    try? await Task.sleep(for: .seconds(1))
                    guard !self.stopping else { return }
                    self.launch()
                }
            }
        }
        do { try child.run(); process = child }
        catch { status = "Engine failed to start"; logs += error.localizedDescription + "\n" }
    }
    func stop() {
        stopping = true
        connected = false
        process?.terminationHandler = nil
        if let process, process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(2)
            while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.025) }
            if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            process.waitUntilExit()
        }
        process = nil
    }
}
