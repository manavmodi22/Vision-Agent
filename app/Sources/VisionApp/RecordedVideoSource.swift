import AVFoundation

/// AVAssetReader emits the same CVPixelBuffer stream as the real capture adapters.
/// Playback is paced by source time; inference never queues or slows playback.
final class RecordedVideoSource: LiveCaptureSource, @unchecked Sendable {
    private let url: URL
    private let publisher: LiveFramePublisher
    private let onEnd: () -> Void
    private let onError: (Error) -> Void
    private let lock = NSLock()
    private var cancelled = false
    private var reader: AVAssetReader?
    private var playback: Task<Void, Never>?
    init(url: URL, publisher: LiveFramePublisher, onEnd: @escaping () -> Void, onError: @escaping (Error) -> Void) {
        self.url = url; self.publisher = publisher; self.onEnd = onEnd; self.onError = onError
    }
    private func locked<T>(_ body: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return body() }
    func start() async throws {
        let asset = AVURLAsset(url: url)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else { throw EngineError.transport("This file has no readable video track.") }
        let transform = try await track.load(.preferredTransform)
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        output.alwaysCopiesSampleData = false
        guard reader.canAdd(output) else { throw EngineError.transport("This video format cannot be decoded locally.") }
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? EngineError.transport("Could not open the recorded video.") }
        let startAllowed = locked { () -> Bool in self.reader = reader; return !cancelled }
        guard startAllowed else { reader.cancelReading(); return }
        playback = Task.detached(priority: .userInitiated) { [self] in
            let start = ContinuousClock.now
            var origin: Double?
            do {
                while !Task.isCancelled && !locked({ cancelled }) {
                    guard let sample = output.copyNextSampleBuffer() else { break }
                    let time = sample.presentationTimeStamp.seconds
                    guard time.isFinite, let pixels = sample.imageBuffer else { continue }
                    if origin == nil { origin = time }
                    let relative = max(0, time - (origin ?? time))
                    try await Task.sleep(until: start.advanced(by: .seconds(relative)), clock: .continuous)
                    guard !locked({ cancelled }) else { return }
                    publisher.offer(pixels, timestamp: relative, transform: transform)
                }
                if locked({ cancelled }) || Task.isCancelled { return }
                if reader.status == .failed { throw reader.error ?? EngineError.transport("Recorded video decoding failed.") }
                await publisher.drain()
                if !locked({ cancelled }) { onEnd() }
            } catch is CancellationError { }
            catch { if !locked({ cancelled }) { onError(error) } }
        }
    }
    func stop() async {
        locked { cancelled = true; reader?.cancelReading() }
        playback?.cancel(); playback = nil
    }
}
