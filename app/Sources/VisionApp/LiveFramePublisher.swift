import AppKit
import CoreImage
import CoreVideo
import Darwin

/// A single mapping, one synchronous writer and at most one HTTP request.
final class LiveMappedBuffer {
    let capacity: Int
    private var address: UnsafeMutableRawPointer?
    init(path: String, capacity: Int) throws {
        guard path.hasPrefix("/"), capacity > 0, capacity <= 32 * 1024 * 1024 else { throw EngineError.protocolError("Invalid live buffer.") }
        let fd = Darwin.open(path, O_RDWR | O_NOFOLLOW)
        guard fd >= 0 else { throw EngineError.transport("Cannot open the engine's live buffer.") }
        defer { Darwin.close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG,
              info.st_uid == getuid(), info.st_size >= capacity, info.st_mode & 0o077 == 0 else {
            throw EngineError.protocolError("The live buffer is not a private file owned by this user.")
        }
        let mapped = mmap(nil, capacity, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0)
        guard mapped != MAP_FAILED, let mapped else { throw EngineError.transport("Cannot map the live buffer.") }
        self.capacity = capacity; address = mapped
    }
    func write(_ data: Data) throws {
        guard let address, data.count <= capacity else { throw EngineError.protocolError("Live buffer is closed or too small.") }
        data.withUnsafeBytes { bytes in if let base = bytes.baseAddress { address.copyMemory(from: base, byteCount: bytes.count) } }
    }
    func close() { if let address { munmap(address, capacity); self.address = nil } }
    deinit { close() }
}

final class LiveFramePublisher: @unchecked Sendable {
    let session: LiveSession
    private let client: EngineClient
    private let endpoint: String
    private let buffer: LiveMappedBuffer
    private let context = CIContext(options: [.cacheIntermediates: false])
    private let lock = NSLock()
    private var gate: LiveFrameGate
    private let onResult: (LiveFrameResponse, CGImage, Int, Int) -> Void
    private let onError: (Error) -> Void
    init(session: LiveSession, client: EngineClient,
         onResult: @escaping (LiveFrameResponse, CGImage, Int, Int) -> Void, onError: @escaping (Error) -> Void) throws {
        self.session = session; self.client = client
        endpoint = "/projects/\(session.projectId)/live/\(session.sessionId)"
        buffer = try LiveMappedBuffer(path: session.sharedMemoryPath, capacity: session.capacityBytes)
        gate = LiveFrameGate(fps: session.sampleFps)
        self.onResult = onResult; self.onError = onError
    }
    var counts: (dropped: Int, sampledOut: Int) { locked { (gate.dropped, gate.sampledOut) } }
    private func locked<T>(_ body: () throws -> T) rethrows -> T { lock.lock(); defer { lock.unlock() }; return try body() }
    func didDrop() { locked { gate.didDrop() } }
    func beginStop() { locked { gate.stop() } }
    /// Invoked directly by capture's serial callback queue, before creating any Task.
    func offer(_ pixelBuffer: CVPixelBuffer, timestamp: Double, transform: CGAffineTransform = .identity) {
        var work: (LiveFrameMetadata, CGImage)?
        do {
            work = try locked {
                guard let ticket = gate.claim(timestamp: timestamp) else { return nil }
                do {
                    var image = CIImage(cvPixelBuffer: pixelBuffer).transformed(by: transform)
                    image = image.transformed(by: .init(translationX: -image.extent.minX, y: -image.extent.minY))
                    let scale = min(1, 1280 / max(image.extent.width, image.extent.height))
                    image = image.transformed(by: .init(scaleX: scale, y: scale))
                    let width = max(1, Int(image.extent.width)), height = max(1, Int(image.extent.height))
                    let layout = try LiveFrameLayout(width: width, height: height, bytesPerRow: width * 4, capacity: buffer.capacity)
                    var data = Data(count: layout.byteCount)
                    let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
                    data.withUnsafeMutableBytes { bytes in
                        context.render(image, toBitmap: bytes.baseAddress!, rowBytes: layout.bytesPerRow,
                                       bounds: CGRect(x: 0, y: 0, width: width, height: height), format: .BGRA8, colorSpace: colorSpace)
                    }
                    try buffer.write(data)
                    let bitmap = CGBitmapInfo.byteOrder32Little.union(CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedFirst.rawValue))
                    guard let provider = CGDataProvider(data: data as CFData),
                          let preview = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                                bytesPerRow: layout.bytesPerRow, space: colorSpace, bitmapInfo: bitmap,
                                                provider: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent) else {
                        throw EngineError.protocolError("Cannot construct live preview.")
                    }
                    return (LiveFrameMetadata(sequence: ticket.sequence, width: width, height: height,
                                              bytesPerRow: layout.bytesPerRow, timestampS: ticket.timestamp), preview)
                } catch { gate.finish(); gate.stop(); throw error }
            }
        } catch { onError(error); return }
        guard let (metadata, preview) = work else { return }
        Task { [self] in
            do {
                let response: LiveFrameResponse = try await client.send("POST", endpoint + "/frames", value: metadata, as: LiveFrameResponse.self)
                let deliver = locked { () -> Bool in
                    let wasAccepting = gate.accepting
                    if response.state != "running" { gate.stop() }
                    gate.finish(); return wasAccepting
                }
                if deliver { let count = counts; onResult(response, preview, count.dropped, count.sampledOut) }
            } catch {
                let deliver = locked { () -> Bool in let accepting = gate.accepting; gate.stop(); gate.finish(); return accepting }
                if deliver { onError(error) }
            }
        }
    }
    func drain() async {
        while !Task.isCancelled && locked({ gate.inFlight }) {
            do { try await Task.sleep(for: .milliseconds(20)) } catch { return }
        }
    }
    func stop() async throws -> LiveSession {
        beginStop()
        // Stop is independent of inference; the engine abandons persistence for in-flight work.
        let status: LiveSession = try await client.request("POST", endpoint + "/stop", body: [:])
        // An outstanding request retains this publisher. No callback can write after beginStop.
        locked { buffer.close() }
        return status
    }
}
