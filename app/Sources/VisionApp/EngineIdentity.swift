import Foundation
import CryptoKit

struct SupervisorHealth: Decodable {
    let runtime: EngineRuntimeIdentity?
}
struct EngineRuntimeIdentity: Decodable {
    let dataDir: String
    let python: String
    let packageRoot: String
    let buildId: String
    enum CodingKeys: String, CodingKey { case dataDir = "data_dir", python, packageRoot = "package_root", buildId = "build_id" }
    func matches(data: URL, executable: URL, packages: URL, build: String) -> Bool {
        func resolved(_ value: String) -> String { URL(fileURLWithPath: value).resolvingSymlinksInPath().path }
        return resolved(dataDir) == data.resolvingSymlinksInPath().path
            && resolved(python) == executable.resolvingSymlinksInPath().path
            && resolved(packageRoot) == packages.appendingPathComponent("engine").resolvingSymlinksInPath().path
            && buildId == build
    }
}
enum EngineBuildIdentity {
    static func sourceHash(_ parent: URL) throws -> String {
        var digest = SHA256()
        let parent = parent.resolvingSymlinksInPath()
        for package in ["agent", "engine", "mcp_server", "spec"] {
            let directory = parent.appendingPathComponent(package)
            guard let files = FileManager.default.enumerator(at: directory, includingPropertiesForKeys: [.isRegularFileKey]) else {
                throw EngineError.protocolError("Missing engine package: \(package)")
            }
            let skillRoot = directory.appendingPathComponent("skills/packages").path + "/"
            let paths = files.compactMap { ($0 as? URL)?.resolvingSymlinksInPath() }.filter {
                $0.pathExtension == "py" || (package == "agent" && $0.pathExtension == "md" && $0.path.hasPrefix(skillRoot))
            }.sorted { $0.path < $1.path }
            guard !paths.isEmpty else { throw EngineError.protocolError("Empty engine package: \(package)") }
            for path in paths {
                let relative = package + "/" + String(path.path.dropFirst(directory.path.count + 1))
                digest.update(data: Data(relative.utf8)); digest.update(data: Data([0]))
                digest.update(data: try Data(contentsOf: path)); digest.update(data: Data([0]))
            }
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }
    static func shortHash(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).prefix(6).map { String(format: "%02x", $0) }.joined()
    }
}
