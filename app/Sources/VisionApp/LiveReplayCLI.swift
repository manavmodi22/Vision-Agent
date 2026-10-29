import Foundation
import CoreGraphics
import AppKit

/// No camera/screen APIs are invoked by this real-media integration check.
enum LiveReplayCLI {
    static func runIfRequested() {
        let args = CommandLine.arguments
        guard args.dropFirst().first == "--replay-video" else { return }
        func value(_ flag: String) -> String? { guard let index = args.firstIndex(of: flag), args.indices.contains(index + 1) else { return nil }; return args[index + 1] }
        guard let path = value("--replay-video"), let project = value("--project"), let socket = value("--socket") else {
            FileHandle.standardError.write(Data("Usage: --replay-video FILE --project ID --socket PATH [--preview-only] [--candidate 0] [--duration 30]\n".utf8)); exit(2)
        }
        let duration = min(300, max(1, Double(value("--duration") ?? "30") ?? 30))
        Task.detached {
            let client = EngineClient(socketPath: socket)
            var session: LiveSession?
            do {
                let created: LiveSession = try await client.request("POST", "/projects/\(project)/live", body: [
                    "candidate_index": .number(Double(value("--candidate") ?? "0") ?? 0), "source_kind": .string("recorded_video"),
                    "source_label": .string(URL(fileURLWithPath: path).lastPathComponent), "preview_only": .bool(args.contains("--preview-only"))])
                session = created
                let result = ReplayResult()
                let output = value("--output-dir").map { URL(fileURLWithPath: $0, isDirectory: true) }
                if let output { try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true) }
                let publisher = try LiveFramePublisher(session: created, client: client, onResult: { response, image, dropped, sampled in
                    if let output {
                        do { try ReplayArtifacts.save(image: image, response: response, directory: output) }
                        catch { result.fail(error); return }
                    }
                    result.record(response, dropped: dropped)
                    print("{\"processed_frames\":\(response.processedFrames),\"detections\":\(response.result.detections.count),\"processing_ms\":\(response.processingMs),\"dropped\":\(dropped),\"sampled_out\":\(sampled),\"width\":\(image.width),\"height\":\(image.height),\"state\":\"\(response.state)\"}")
                }, onError: { result.fail($0) })
                let source = RecordedVideoSource(url: URL(fileURLWithPath: path), publisher: publisher, onEnd: { result.end() }, onError: { result.fail($0) })
                try await source.start()
                let until = ContinuousClock.now.advanced(by: .seconds(duration))
                while !result.finished && ContinuousClock.now < until { try await Task.sleep(for: .milliseconds(100)) }
                publisher.beginStop(); await source.stop()
                let stopped = try await publisher.stop()
                if let error = result.error { throw EngineError.transport(error) }
                guard result.frames > 0 else { throw EngineError.transport("Replay produced no processed frames before its time limit.") }
                print("{\"status\":\"passed\",\"session_id\":\"\(created.sessionId)\",\"processed_frames\":\(result.frames),\"retained_frames\":\(stopped.retainedFrames),\"state\":\"\(stopped.state)\"}")
                exit(0)
            } catch {
                if let session { let _: LiveSession? = try? await client.request("POST", "/projects/\(project)/live/\(session.sessionId)/stop", body: [:]) }
                FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1)
            }
        }
        dispatchMain()
    }
}
private final class ReplayResult: @unchecked Sendable {
    private let lock = NSLock()
    private var isFinished = false
    private var errorValue: String?
    private var frameCount = 0
    private func locked<T>(_ operation: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return operation() }
    var finished: Bool { locked { isFinished } }
    var error: String? { locked { errorValue } }
    var frames: Int { locked { frameCount } }
    func record(_ response: LiveFrameResponse, dropped: Int) { locked { frameCount = response.processedFrames; if response.state != "running" { isFinished = true } } }
    func fail(_ error: Error) { locked { errorValue = error.localizedDescription; isFinished = true } }
    func end() { locked { isFinished = true } }
}
