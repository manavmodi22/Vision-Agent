import Foundation

enum EngineIdentityChecks {
    static func run() throws -> Int {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("vision-identity-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        for name in ["agent", "engine", "mcp_server", "spec"] {
            let folder = directory.appendingPathComponent(name)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try Data("# \(name)\n".utf8).write(to: folder.appendingPathComponent("__init__.py"))
        }
        let hash = try EngineBuildIdentity.sourceHash(directory)
        guard hash == "c9f5e4d0f8e04aeb91b4715b27e112e1c5248826182a4582a87dc253aecbd8a4" else {
            throw EngineError.protocolError("Source fingerprint differs from Python contract")
        }
        let skill = directory.appendingPathComponent("agent/skills/packages/count/SKILL.md")
        try FileManager.default.createDirectory(at: skill.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("# Count\n".utf8).write(to: skill)
        guard try EngineBuildIdentity.sourceHash(directory) == "4e5c233111ddec7e6eef3f64677653f981473244b6b40ad345176df3af5c5f94" else {
            throw EngineError.protocolError("Packaged skill fingerprint differs from Python contract")
        }
        try Data("# Count revised\n".utf8).write(to: skill)
        guard try EngineBuildIdentity.sourceHash(directory) == "03935b1cc7b2f294dbbdfa1c385d63b59403fdf4037ae0398a112f8a07a9a8a8" else {
            throw EngineError.protocolError("Edited skill did not update source identity")
        }
        try FileManager.default.removeItem(at: skill)
        try Data("# Unpackaged note\n".utf8).write(to: directory.appendingPathComponent("agent/README.md"))
        guard try EngineBuildIdentity.sourceHash(directory) == hash else { throw EngineError.protocolError("Unpackaged documentation changed runtime identity") }
        let identity = EngineRuntimeIdentity(dataDir: directory.path, python: directory.appendingPathComponent("python").path,
                                            packageRoot: directory.appendingPathComponent("engine").path, buildId: hash)
        guard identity.matches(data: directory, executable: directory.appendingPathComponent("python"), packages: directory, build: hash),
              !identity.matches(data: directory.appendingPathComponent("other"), executable: directory.appendingPathComponent("python"), packages: directory, build: hash),
              !identity.matches(data: directory, executable: directory.appendingPathComponent("python"), packages: directory, build: "stale"),
              !identity.matches(data: directory, executable: directory.appendingPathComponent("other-python"), packages: directory, build: hash) else {
            throw EngineError.protocolError("Engine compatibility checks failed")
        }
        try Data("# edited\n".utf8).write(to: directory.appendingPathComponent("engine/__init__.py"))
        guard try EngineBuildIdentity.sourceHash(directory) != hash else { throw EngineError.protocolError("Edited source did not change identity") }
        let current = directory.appendingPathComponent("current-app"), configured = directory.appendingPathComponent("configured-bridge")
        for executable in [current, configured] {
            try Data("#!/bin/sh\nexit 0\n".utf8).write(to: executable)
            try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: executable.path)
        }
        guard try NativeVisionBridge.executable(environment: [:], appExecutable: current.path) == current.path,
              try NativeVisionBridge.executable(environment: ["VISION_APP_BINARY": configured.path], appExecutable: current.path) == configured.path else { throw EngineError.protocolError("Vision bridge configuration did not select the exact executable") }
        let notExecutable = directory.appendingPathComponent("not-executable")
        try Data("plain file".utf8).write(to: notExecutable)
        for invalid in ["", "relative/bridge", directory.appendingPathComponent("missing").path, directory.path, notExecutable.path] {
            do {
                _ = try NativeVisionBridge.executable(environment: ["VISION_APP_BINARY": invalid], appExecutable: current.path)
                throw EngineError.protocolError("Invalid explicit vision bridge silently fell back")
            } catch EngineError.protocolError(let message) {
                guard message.hasPrefix("VISION_APP_BINARY must name") else { throw EngineError.protocolError(message) }
            }
        }
        return 16
    }
}
