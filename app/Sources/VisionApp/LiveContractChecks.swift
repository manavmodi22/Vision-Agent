import Foundation
import Darwin

enum LiveContractChecks {
    static func run() throws -> Int {
        var count = 0
        func check(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Live contract check failed: " + message) }; count += 1
        }
        let valid = try LiveFrameLayout(width: 1280, height: 720, bytesPerRow: 5120, capacity: 32 * 1024 * 1024)
        try check(valid.byteCount == 3_686_400, "BGRA layout byte count")
        func rejected(_ width: Int, _ height: Int, _ row: Int, _ capacity: Int) -> Bool {
            do { _ = try LiveFrameLayout(width: width, height: height, bytesPerRow: row, capacity: capacity); return false } catch { return true }
        }
        try check(rejected(0, 10, 40, 400), "zero width rejection")
        try check(rejected(10, 10, 39, 400), "short stride rejection")
        try check(rejected(10, 10, 41, 500), "unaligned stride rejection")
        try check(rejected(8193, 1, 8193 * 4, 40000), "dimension bound")
        try check(rejected(8192, 8192, Int.max - 3, Int.max), "overflow safe capacity check")
        var gate = LiveFrameGate(fps: 2)
        let first = gate.claim(timestamp: 100)
        try check(first?.sequence == 1 && first?.timestamp == 0, "first timestamp normalization")
        try check(gate.claim(timestamp: 100.5) == nil && gate.dropped == 1, "busy frame is dropped instead of queued")
        gate.finish()
        try check(gate.claim(timestamp: 100.1) == nil && gate.sampledOut == 1, "sample rate throttle")
        let second = gate.claim(timestamp: 100.5)
        try check(second?.sequence == 2 && second?.timestamp == 0.5, "accepted sequence ignores dropped frames")
        gate.stop()
        try check(gate.inFlight && gate.claim(timestamp: 101) == nil, "stop rejects writes while request is in flight")
        gate.finish()
        try check(!gate.inFlight && gate.claim(timestamp: 102) == nil, "completion never reopens a stopped publisher")
        var timestamps = LiveFrameGate(fps: 30)
        try check(timestamps.claim(timestamp: .nan) == nil && timestamps.claim(timestamp: -1) == nil, "invalid timestamp rejection")
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("vision-live-check-" + UUID().uuidString)
        FileManager.default.createFile(atPath: temp.path, contents: Data(count: 64), attributes: [.posixPermissions: 0o600])
        defer { try? FileManager.default.removeItem(at: temp) }
        let mapped = try LiveMappedBuffer(path: temp.path, capacity: 64)
        let bytes = Data([2, 3, 4, 255, 7, 8, 9, 255])
        try mapped.write(bytes)
        try check(try Data(contentsOf: temp).prefix(8) == bytes, "shared BGRA bytes reach the actual mapped file")
        mapped.close()
        var closedRejected = false
        do { try mapped.write(bytes) } catch { closedRejected = true }
        try check(closedRejected, "closed mapping rejects writes")
        let wire = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(LiveFrameMetadata(sequence: 1, width: 2, height: 1, bytesPerRow: 8, timestampS: 0)))
        try check(wire.object["bytes_per_row"] == .number(8) && wire.object["timestamp_s"] == .number(0), "metadata wire contract")
        return count
    }
}
