import Foundation
import CryptoKit
import Darwin

/// Reads only the selected task's immutable evidence, through non-following directory descriptors.
struct InvestigationArtifacts {
    let dataRoot: URL
    let projectID: String
    let taskID: String
    private func matches(_ value: String, _ pattern: String) -> Bool { value.range(of: pattern, options: .regularExpression) != nil }
    func artifact(_ reference: [String: JSONValue], mime: String) throws -> Data {
        guard let id = reference["artifact_id"]?.string, let hash = reference["sha256"]?.string,
              matches(hash, "^[0-9a-f]{64}$"), reference["mime_type"] == .string(mime),
              id == hash + (mime == "image/png" ? ".png" : ".json"),
              ["image/png", "application/json"].contains(mime) else { throw invalid("Invalid artifact reference") }
        let data = try read(["artifacts", id], hash: hash)
        guard reference["bytes"] == .number(Double(data.count)) else { throw invalid("Artifact size changed") }
        return data
    }
    func previewImage(_ frame: FrameResult, draft: InvestigationDraftPreview) throws -> Data {
        guard matches(draft.revisionID, "^[0-9a-f]{32}$"), let hash = frame.sourceImageSHA256,
              case .array(let refs) = draft.observation.payload["input_refs"],
              let input = refs.map(\.object).first(where: { $0["preview_path"] == .string(frame.imagePath) }),
              input["preview_source_sha256"] == .string(hash), input["source_sha256"] == .string(hash) else {
            throw invalid("Preview source receipt does not match this frame")
        }
        let name = URL(fileURLWithPath: frame.imagePath).lastPathComponent
        let parts = ["workflows", draft.revisionID, "media", name]
        let expected = taskRoot.appendingPathComponent(parts.joined(separator: "/")).path
        guard frame.imagePath == expected, matches(name, "^[0-9]{2}-[A-Za-z0-9_-]+\\.[A-Za-z0-9]+$") else {
            throw invalid("Preview image is outside its selected workflow revision")
        }
        return try read(parts, hash: hash)
    }
    private var taskRoot: URL {
        dataRoot.standardizedFileURL.resolvingSymlinksInPath().appendingPathComponent("projects/\(projectID)/investigations/\(taskID)")
    }
    private func invalid(_ message: String) -> EngineError { .protocolError(message) }
    private func read(_ parts: [String], hash: String) throws -> Data {
        guard matches(projectID, "^[A-Za-z0-9_-]{1,128}$"), matches(taskID, "^[0-9a-f]{32}$"), matches(hash, "^[0-9a-f]{64}$") else {
            throw invalid("Invalid task-owned evidence identity")
        }
        let components = ["projects", projectID, "investigations", taskID] + parts
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.contains("/") && !$0.contains("\0") }) else { throw invalid("Invalid evidence path") }
        var directory = Darwin.open(dataRoot.standardizedFileURL.resolvingSymlinksInPath().path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
        guard directory >= 0 else { throw invalid("Evidence storage is unavailable") }
        defer { Darwin.close(directory) }
        for component in components.dropLast() {
            let child = openat(directory, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
            guard child >= 0 else { throw invalid("Evidence directory is unavailable or a symbolic link") }
            Darwin.close(directory); directory = child
        }
        let file = openat(directory, components.last!, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard file >= 0 else { throw invalid("Evidence file is unavailable or a symbolic link") }
        defer { Darwin.close(file) }
        var info = stat()
        guard fstat(file, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG, info.st_size >= 0, info.st_size <= 64 * 1024 * 1024 else { throw invalid("Evidence is not a bounded regular file") }
        var data = Data(); var chunk = [UInt8](repeating: 0, count: 65536)
        while true {
            let count = Darwin.read(file, &chunk, chunk.count)
            guard count >= 0 else { throw invalid("Could not read evidence") }
            if count == 0 { break }
            guard data.count + count <= 64 * 1024 * 1024 else { throw invalid("Evidence exceeds the size limit") }
            data.append(contentsOf: chunk.prefix(count))
        }
        guard SHA256.hash(data: data).map({ String(format: "%02x", $0) }).joined() == hash else { throw invalid("Evidence content hash changed") }
        return data
    }
}

enum InvestigationProbePresentation {
    static func readings(_ items: [[String: JSONValue]]) -> [DisplayReading] {
        items.enumerated().compactMap { index, item in
            guard let reading: ReadingObservation = InvestigationPresentation.decode(.object(item)) else { return nil }
            return DisplayReading(id: item["item_id"]?.string ?? "observation-\(index)", blockID: "", index: index,
                                  observation: ReadingGeometry.mapped(reading, transform: [0, 0, 1, 1]))
        }
    }
    static func detections(_ items: [[String: JSONValue]]) -> [Detection] {
        items.compactMap { item in
            guard let value: Detection = InvestigationPresentation.decode(.object(item)), value.box.count == 4,
                  value.box.allSatisfy({ $0.isFinite && (0...1).contains($0) }), value.box[0] < value.box[2], value.box[1] < value.box[3] else { return nil }
            return value
        }
    }
}
