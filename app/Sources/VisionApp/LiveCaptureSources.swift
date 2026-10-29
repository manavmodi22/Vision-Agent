import AVFoundation
import ScreenCaptureKit

protocol LiveCaptureSource: AnyObject {
    func start() async throws
    func stop() async
}

final class CameraCaptureSource: NSObject, LiveCaptureSource, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let device: AVCaptureDevice
    private let publisher: LiveFramePublisher
    private let session = AVCaptureSession()
    private let output = AVCaptureVideoDataOutput()
    private let queue = DispatchQueue(label: "vision.capture.camera")
    private let onError: (Error) -> Void
    private var observer: NSObjectProtocol?
    private var stopped = false
    init(device: AVCaptureDevice, publisher: LiveFramePublisher, onError: @escaping (Error) -> Void) {
        self.device = device; self.publisher = publisher; self.onError = onError
    }
    func start() async throws {
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            throw EngineError.transport("Camera access was not granted. Allow VisionApp in System Settings → Privacy & Security → Camera.")
        }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            queue.async { [self] in
                do {
                    guard !stopped else { continuation.resume(); return }
                    session.beginConfiguration()
                    do {
                    if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
                    let input = try AVCaptureDeviceInput(device: device)
                    guard session.canAddInput(input), session.canAddOutput(output) else {
                        throw EngineError.transport("The selected camera cannot provide video.")
                    }
                    session.addInput(input)
                    output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
                    output.alwaysDiscardsLateVideoFrames = true
                    output.setSampleBufferDelegate(self, queue: queue)
                    session.addOutput(output)
                    } catch { session.commitConfiguration(); throw error }
                    session.commitConfiguration()
                    observer = NotificationCenter.default.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: session, queue: nil) { [weak self] note in
                        let error = note.userInfo?[AVCaptureSessionErrorKey] as? Error ?? EngineError.transport("Camera capture stopped unexpectedly.")
                        self?.onError(error)
                    }
                    session.startRunning()
                    guard session.isRunning else { throw EngineError.transport("The camera did not start.") }
                    continuation.resume()
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
    func stop() async {
        await withCheckedContinuation { continuation in
            queue.async { [self] in
                stopped = true
                output.setSampleBufferDelegate(nil, queue: nil)
                if session.isRunning { session.stopRunning() }
                if let observer { NotificationCenter.default.removeObserver(observer); self.observer = nil }
                continuation.resume()
            }
        }
    }
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let pixels = sampleBuffer.imageBuffer else { return }
        publisher.offer(pixels, timestamp: sampleBuffer.presentationTimeStamp.seconds)
    }
    func captureOutput(_ output: AVCaptureOutput, didDrop sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) { publisher.didDrop() }
}

final class ScreenCaptureSource: NSObject, LiveCaptureSource, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    private let filter: SCContentFilter
    private let publisher: LiveFramePublisher
    private let onError: (Error) -> Void
    private var stream: SCStream?
    private let lock = NSLock()
    private var stopped = false
    private func locked<T>(_ operation: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return operation() }
    private let queue = DispatchQueue(label: "vision.capture.screen")
    init(filter: SCContentFilter, publisher: LiveFramePublisher, onError: @escaping (Error) -> Void) {
        self.filter = filter; self.publisher = publisher; self.onError = onError
    }
    func start() async throws {
        let config = SCStreamConfiguration()
        let size = filter.contentRect.size
        let scale = min(1, 1280 / max(1, max(size.width, size.height)))
        config.width = max(1, Int(size.width * scale)); config.height = max(1, Int(size.height * scale))
        config.pixelFormat = kCVPixelFormatType_32BGRA
        config.minimumFrameInterval = CMTime(seconds: 1 / max(1, publisher.session.sampleFps), preferredTimescale: 60000)
        config.queueDepth = 3; config.capturesAudio = false; config.showsCursor = true
        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        guard locked({ () -> Bool in if stopped { return false }; self.stream = stream; return true }) else { return }
        try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
        try await stream.startCapture()
        if locked({ stopped }) { try? await stream.stopCapture() }
    }
    func stop() async {
        guard let stream = locked({ () -> SCStream? in stopped = true; let value = self.stream; self.stream = nil; return value }) else { return }
        try? await stream.stopCapture()
        try? stream.removeStreamOutput(self, type: .screen)
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onError(error) }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sampleBuffer.isValid, let pixels = sampleBuffer.imageBuffer,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let raw = attachments.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete else { return }
        publisher.offer(pixels, timestamp: sampleBuffer.presentationTimeStamp.seconds)
    }
}
