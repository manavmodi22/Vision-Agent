import Foundation
import CoreGraphics

/// A CLI verification path for CommandLineTools installations without XCTest.
enum NativeSelfTests {
    @MainActor static func runIfRequested() {
        CLIOutputChecks.runProbeIfRequested()
        guard CommandLine.arguments.dropFirst().first == "--self-test" else { return }
        do {
            var checks = 0
            func require(_ condition: Bool, _ message: String) throws {
                guard condition else { throw EngineError.protocolError("Self-test failed: " + message) }
                checks += 1
            }
            let normal = try HTTPResponse.parse(Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}".utf8))
            try require(normal.status == 200 && normal.body == Data("{}".utf8), "HTTP content length")
            let chunked = try HTTPResponse.parse(Data("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n".utf8))
            try require(chunked.body == Data("{}".utf8), "HTTP chunked response")
            var rejected = false
            do { _ = try HTTPResponse.parse(Data("HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n{}".utf8)) }
            catch { rejected = true }
            try require(rejected, "truncated response rejection")
            let rect = ImageGeometry.fittedRect(image: CGSize(width: 800, height: 400), container: CGSize(width: 600, height: 600))
            try require(rect == CGRect(x: 0, y: 150, width: 600, height: 300), "letterbox geometry")
            try require(ImageGeometry.normalizedBox(start: CGPoint(x: 150, y: 225), end: CGPoint(x: 450, y: 375), rect: rect) == [0.25, 0.25, 0.75, 0.75], "normalized label box")
            try require(ImageGeometry.normalizedBox(start: CGPoint(x: 100, y: 10), end: CGPoint(x: 200, y: 300), rect: rect) == nil, "reject draw outside image")
            let pipeline = try JSONDecoder().decode(Pipeline.self, from: Data("""
            {"spec_version":"0.1","name":"count","inputs":{"source":{"type":"image_folder","path":"media"}},"blocks":[{"id":"sample","type":"frame_sample","params":{"fps":2},"in":{"frames":"$inputs.source"}}],"eval":{"metric":"count_mae","target":0.5,"set":"eval"}}
            """.utf8))
            try require(pipeline.blocks[0].connections?["frames"] == .string("$inputs.source"), "wire-key decoding")
            let encoded = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(pipeline))
            try require(encoded.object["spec_version"] == .string("0.1"), "wire-key encoding")
            checks += try AlertContractChecks.run()
            checks += try AnnotationContractChecks.run()
            checks += try LiveContractChecks.run()
            checks += try AgentContractChecks.run()
            checks += try EvaluationContractChecks.run()
            checks += try EvaluationEvidenceChecks.run()
            checks += try ProvisioningContractChecks.run()
            checks += try EngineIdentityChecks.run()
            checks += try PlatformContractChecks.run()
            checks += try PreviewOutcomeChecks.run()
            checks += try NativeOCRChecks.run()
            checks += try ReadingEvidenceChecks.run()
            checks += try TextComparisonChecks.run()
            checks += try TextRegionChecks.run()
            checks += try CLIOutputChecks.run()
            checks += try CandidatePreviewChecks.run()
            checks += try PlatformContractChecks.checkFiles(Array(CommandLine.arguments.dropFirst(2)))
            print("{\"status\":\"passed\",\"checks\":\(checks)}")
            exit(0)
        } catch {
            FileHandle.standardError.write(Data((error.localizedDescription + "\n").utf8)); exit(1)
        }
    }
}
