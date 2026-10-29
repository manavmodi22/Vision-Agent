import AppKit
import AVFoundation
import ScreenCaptureKit
import UniformTypeIdentifiers

@MainActor
final class LiveCaptureModel: NSObject, ObservableObject, SCContentSharingPickerObserver {
    @Published var sourceKind = LiveSourceKind.recordedVideo
    @Published var videoURL: URL?
    @Published var cameras: [AVCaptureDevice] = []
    @Published var cameraID = ""
    @Published var screenSelected = false
    @Published var previewOnly = true
    @Published private(set) var state = "idle"
    @Published private(set) var session: LiveSession?
    @Published private(set) var frame: FrameResult?
    @Published private(set) var image: NSImage?
    @Published private(set) var droppedFrames = 0
    @Published private(set) var sampledFrames = 0
    @Published private(set) var processingMs = 0.0
    @Published private(set) var processingFps = 0.0
    @Published private(set) var processedFrames = 0
    @Published private(set) var retainedFrames = 0
    @Published private(set) var retainedBytes = 0
    @Published private(set) var error: String?
    @Published private(set) var pickingScreen = false
    private let client: EngineClient
    private var filter: SCContentFilter?
    private var source: LiveCaptureSource?
    private var publisher: LiveFramePublisher?
    private var startingTask: Task<Void, Never>?
    private var statusTask: Task<Void, Never>?
    private var generation = UUID()
    private var firstSubmissionAt: ContinuousClock.Instant?
    private var observerAdded = false
    var active: Bool { ["starting", "running", "stopping"].contains(state) }
    var ready: Bool {
        switch sourceKind { case .recordedVideo: return videoURL != nil; case .camera: return cameras.contains { $0.uniqueID == cameraID }; case .screenCapture: return screenSelected }
    }
    var sourceLabel: String {
        switch sourceKind { case .recordedVideo: return videoURL?.lastPathComponent ?? "Choose a video"; case .camera: return cameras.first { $0.uniqueID == cameraID }?.localizedName ?? "Choose a camera"; case .screenCapture: return screenSelected ? "System-selected display or window" : "Choose a display or window" }
    }
    init(client: EngineClient) { self.client = client; super.init() }
    func chooseVideo() {
        guard !active else { return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.movie]; panel.allowsMultipleSelection = false
        panel.message = "Replay this video through the live frame pipeline. Its images are not added to your dataset."
        if panel.runModal() == .OK { videoURL = panel.url }
    }
    func findCameras() {
        guard !active else { return }
        cameras = AVCaptureDevice.DiscoverySession(deviceTypes: [.builtInWideAngleCamera, .external], mediaType: .video, position: .unspecified).devices
        if !cameras.contains(where: { $0.uniqueID == cameraID }) { cameraID = cameras.first?.uniqueID ?? "" }
        if cameras.isEmpty { error = "No cameras are available. Connect a camera and refresh." }
    }
    func chooseScreen() {
        guard !active else { return }
        let picker = SCContentSharingPicker.shared
        if !observerAdded { picker.add(self); observerAdded = true }
        var config = SCContentSharingPickerConfiguration()
        config.allowedPickerModes = [.singleDisplay, .singleWindow]; config.allowsChangingSelectedContent = false
        picker.defaultConfiguration = config; picker.isActive = true; pickingScreen = true
        picker.present()
    }
    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didCancelFor stream: SCStream?) {
        Task { @MainActor in self.closePicker() }
    }
    nonisolated func contentSharingPicker(_ picker: SCContentSharingPicker, didUpdateWith filter: SCContentFilter, for stream: SCStream?) {
        Task { @MainActor in
            guard !self.active else { return }
            self.filter = filter; self.screenSelected = true; self.pickingScreen = false
        }
    }
    nonisolated func contentSharingPickerStartDidFailWithError(_ error: Error) {
        Task { @MainActor in self.error = error.localizedDescription; self.pickingScreen = false }
    }
    func start(projectID: String, candidateIndex: Int) {
        guard !active, ready else { return }
        let token = UUID(); generation = token; state = "starting"; error = nil
        session = nil; frame = nil; image = nil; processedFrames = 0; droppedFrames = 0; sampledFrames = 0; retainedFrames = 0; retainedBytes = 0
        processingMs = 0; processingFps = 0; firstSubmissionAt = nil
        let kind = sourceKind, label = sourceLabel, preview = previewOnly
        startingTask = Task { [weak self] in
            guard let self else { return }
            do {
                let session: LiveSession = try await client.request("POST", "/projects/\(projectID)/live", body: ["candidate_index": .number(Double(candidateIndex)), "source_kind": .string(kind.rawValue), "source_label": .string(label), "preview_only": .bool(preview)])
                guard generation == token else {
                    let _: LiveSession? = try? await client.request("POST", "/projects/\(projectID)/live/\(session.sessionId)/stop", body: [:]); return
                }
                self.session = session
                let failure: (Error) -> Void = { [weak self] error in Task { @MainActor in await self?.fail(error, token: token) } }
                let publisher = try LiveFramePublisher(session: session, client: client, onResult: { [weak self] response, image, dropped, sampled in
                    Task { @MainActor in await self?.receive(response, image: image, dropped: dropped, sampled: sampled, token: token) }
                }, onError: failure)
                self.publisher = publisher
                let source: LiveCaptureSource
                switch kind {
                case .recordedVideo:
                    guard let videoURL else { throw EngineError.transport("Select a recorded video.") }
                    source = RecordedVideoSource(url: videoURL, publisher: publisher, onEnd: { [weak self] in Task { @MainActor in guard let self, self.generation == token else { return }; await self.stop() } }, onError: failure)
                case .camera:
                    guard let device = cameras.first(where: { $0.uniqueID == self.cameraID }) else { throw EngineError.transport("Select a camera.") }
                    source = CameraCaptureSource(device: device, publisher: publisher, onError: failure)
                case .screenCapture:
                    guard let filter else { throw EngineError.transport("Select a display or window with the system picker.") }
                    source = ScreenCaptureSource(filter: filter, publisher: publisher, onError: failure)
                }
                self.source = source; firstSubmissionAt = .now
                try await source.start()
                guard generation == token else { await source.stop(); return }
                state = "running"; startStatusPolling(token: token)
            } catch {
                guard generation == token else { return }
                self.error = error.localizedDescription
                await cleanup(); state = "failed"
            }
        }
    }
    private func receive(_ response: LiveFrameResponse, image: CGImage, dropped: Int, sampled: Int, token: UUID) async {
        guard generation == token, state != "stopping" else { return }
        frame = response.result; self.image = NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
        processedFrames = response.processedFrames; processingMs = response.processingMs
        droppedFrames = dropped; sampledFrames = sampled; retainedFrames = response.retainedFrames; retainedBytes = response.retainedBytes
        if let firstSubmissionAt {
            let duration = firstSubmissionAt.duration(to: .now).components
            let elapsed = Double(duration.seconds) + Double(duration.attoseconds) / 1e18
            processingFps = elapsed > 0 ? Double(processedFrames) / elapsed : 0
        }
        if response.state != "running" { await stop(finalState: response.state) }
    }
    private func fail(_ error: Error, token: UUID) async {
        guard generation == token, state != "stopping" else { return }
        self.error = error.localizedDescription; await stop(finalState: "failed")
    }
    private func startStatusPolling(token: UUID) {
        statusTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled, let self, self.generation == token, let session = self.session else { return }
                if let count = self.publisher?.counts { self.droppedFrames = count.dropped; self.sampledFrames = count.sampledOut }
                do {
                    let status: LiveSession = try await self.client.request("GET", "/projects/\(session.projectId)/live/\(session.sessionId)")
                    guard self.generation == token else { return }
                    self.session = status
                    if status.state != "running" { self.error = status.error; await self.stop(finalState: status.state); return }
                } catch { await self.fail(error, token: token); return }
            }
        }
    }
    private func cleanup() async {
        statusTask?.cancel(); statusTask = nil
        let source = self.source, publisher = self.publisher
        publisher?.beginStop(); self.source = nil; self.publisher = nil
        await source?.stop()
        if let publisher {
            do { session = try await publisher.stop() } catch { self.error = self.error ?? error.localizedDescription }
        } else if let session, session.state == "running" {
            let _: LiveSession? = try? await client.request("POST", "/projects/\(session.projectId)/live/\(session.sessionId)/stop", body: [:])
        }
        closePicker()
    }
    func stop(finalState: String = "stopped") async {
        if state == "stopping" {
            while state == "stopping", !Task.isCancelled {
                do { try await Task.sleep(for: .milliseconds(20)) } catch { return }
            }; return
        }
        let start = startingTask; startingTask = nil
        generation = UUID(); state = "stopping"
        await cleanup(); await start?.value
        state = finalState
    }
    func closePicker() {
        guard observerAdded else { return }
        let picker = SCContentSharingPicker.shared; picker.remove(self); picker.isActive = false
        observerAdded = false; pickingScreen = false; filter = nil; screenSelected = false
    }
}
