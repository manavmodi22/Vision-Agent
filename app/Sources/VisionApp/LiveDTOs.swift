import Foundation

struct LiveSession: Codable {
    let sessionId: String
    let projectId: String
    let state: String
    let sharedMemoryPath: String
    let capacityBytes: Int
    let previewOnly: Bool
    let sourceKind: String
    let sourceLabel: String
    let processedFrames: Int
    let retainedFrames: Int
    let retainedBytes: Int
    let maxRetainedFrames: Int
    let maxRetainedBytes: Int
    let sampleFps: Double
    let maxDurationS: Double
    let error: String?
    let warnings: [String]
    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id", projectId = "project_id", state, sharedMemoryPath = "shared_memory_path"
        case capacityBytes = "capacity_bytes", previewOnly = "preview_only", sourceKind = "source_kind", sourceLabel = "source_label"
        case processedFrames = "processed_frames", retainedFrames = "retained_frames", retainedBytes = "retained_bytes"
        case maxRetainedFrames = "max_retained_frames", maxRetainedBytes = "max_retained_bytes", sampleFps = "sample_fps"
        case maxDurationS = "max_duration_s", error, warnings
    }
}
struct LiveFrameMetadata: Codable {
    let sequence: Int
    let width: Int
    let height: Int
    let bytesPerRow: Int
    let timestampS: Double
    enum CodingKeys: String, CodingKey { case sequence, width, height, bytesPerRow = "bytes_per_row", timestampS = "timestamp_s" }
}
struct LiveFrameResponse: Decodable {
    let sessionId: String
    let state: String
    let result: FrameResult
    let processingMs: Double
    let processedFrames: Int
    let retainedFrames: Int
    let retainedBytes: Int
    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id", state, result, processingMs = "processing_ms", processedFrames = "processed_frames"
        case retainedFrames = "retained_frames", retainedBytes = "retained_bytes"
    }
}
enum LiveSourceKind: String, CaseIterable, Identifiable {
    case recordedVideo = "recorded_video", camera, screenCapture = "screen_capture"
    var id: String { rawValue }
    var label: String { switch self { case .recordedVideo: return "Recorded video"; case .camera: return "Camera"; case .screenCapture: return "Display or window" } }
}

/// Pure gate: callers serialize access. No pending-frame slot or unbounded task queue.
struct LiveFrameGate {
    private(set) var accepting = true
    private(set) var inFlight = false
    private(set) var sequence = 0
    private(set) var dropped = 0
    private(set) var sampledOut = 0
    private var origin: Double?
    private var lastTimestamp: Double?
    let fps: Double
    mutating func claim(timestamp: Double) -> (sequence: Int, timestamp: Double)? {
        guard accepting, timestamp.isFinite, timestamp >= 0 else { return nil }
        if origin == nil { origin = timestamp }
        let normalized = timestamp - (origin ?? timestamp)
        if let lastTimestamp, normalized - lastTimestamp < 1 / max(0.01, fps) - 0.000001 { sampledOut += 1; return nil }
        guard !inFlight else { dropped += 1; return nil }
        inFlight = true; sequence += 1; lastTimestamp = normalized
        return (sequence, normalized)
    }
    mutating func didDrop() { if accepting { dropped += 1 } }
    mutating func finish() { inFlight = false }
    mutating func stop() { accepting = false }
}
struct LiveFrameLayout {
    let width: Int, height: Int, bytesPerRow: Int, byteCount: Int
    init(width: Int, height: Int, bytesPerRow: Int, capacity: Int) throws {
        guard width > 0, height > 0, width <= 8192, height <= 8192,
              bytesPerRow >= width * 4, bytesPerRow % 4 == 0,
              bytesPerRow <= capacity / height else {
            throw EngineError.protocolError("The BGRA frame does not fit the shared-memory buffer.")
        }
        self.width = width; self.height = height; self.bytesPerRow = bytesPerRow; byteCount = bytesPerRow * height
    }
}
