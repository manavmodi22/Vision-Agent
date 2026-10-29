import XCTest
@testable import VisionApp

final class NativeTests: XCTestCase {
    func testAnnotationContracts() throws { XCTAssertEqual(try AnnotationContractChecks.run(), 18) }
    func testAlertContracts() throws { XCTAssertEqual(try AlertContractChecks.run(), 11) }
    func testContentLengthResponse() throws {
        let data = Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}".utf8)
        let result = try HTTPResponse.parse(data)
        XCTAssertEqual(result.status, 200)
        XCTAssertEqual(result.body, Data("{}".utf8))
    }
    func testRejectsTruncatedResponse() {
        let data = Data("HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n{}".utf8)
        XCTAssertThrowsError(try HTTPResponse.parse(data))
    }
    func testChunkedResponse() throws {
        let data = Data("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n".utf8)
        XCTAssertEqual(try HTTPResponse.parse(data).body, Data("{}".utf8))
    }
    func testLetterboxedCoordinates() {
        let rect = ImageGeometry.fittedRect(image: CGSize(width: 800, height: 400), container: CGSize(width: 600, height: 600))
        XCTAssertEqual(rect, CGRect(x: 0, y: 150, width: 600, height: 300))
        let box = ImageGeometry.normalizedBox(start: CGPoint(x: 150, y: 225), end: CGPoint(x: 450, y: 375), rect: rect)
        XCTAssertEqual(box, [0.25, 0.25, 0.75, 0.75])
        XCTAssertNil(ImageGeometry.normalizedBox(start: CGPoint(x: 100, y: 10), end: CGPoint(x: 200, y: 300), rect: rect))
    }
    func testPipelinePreservesWireKeys() throws {
        let json = Data("""
        {"spec_version":"0.1","name":"count","inputs":{"source":{"type":"image_folder","path":"media"}},"blocks":[{"id":"sample","type":"frame_sample","params":{"fps":2},"in":{"frames":"$inputs.source"}}],"eval":{"metric":"count_mae","target":0.5,"set":"eval"}}
        """.utf8)
        let pipeline = try JSONDecoder().decode(Pipeline.self, from: json)
        XCTAssertEqual(pipeline.blocks[0].connections?["frames"], .string("$inputs.source"))
        let encoded = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(pipeline))
        XCTAssertEqual(encoded.object["spec_version"], .string("0.1"))
    }
}
