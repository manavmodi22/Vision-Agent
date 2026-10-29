# Native live capture

Run offers recorded video, camera, and a system-selected display or window. No source is enumerated or started on launch. Camera discovery requires a click; camera authorization is requested only by Start. Screen selection uses Apple's content-sharing picker, restricted to one display or window. Capture starts only after a separate Start action. Audio is never requested or captured.

Preview is the default output mode and persists no evidence or alerts. Approved recording uses the engine's deployment and alert gates; recording stops at the engine's retention limit rather than deleting evidence. The UI shows the negotiated sample rate, session limit, accepted count, actual wall-time processing FPS, inference duration, busy drops, sampled-out frames, and retained bytes. Its overlay belongs to the exact submitted frame that produced the response.

## Data path and ownership

All three adapters deliver CVPixelBuffer frames to LiveFramePublisher. AVCaptureVideoDataOutput discards late camera frames; ScreenCaptureKit has a bounded queue. AVAssetReader replays recorded frames against source presentation timestamps and applies the track transform. Replay continues at media speed while busy frames are dropped, exercising the same publisher as live capture.

A locked gate claims the single in-flight slot before image conversion or task allocation. It normalizes the first timestamp to zero, enforces the server's sample rate, and rejects callbacks while inference is outstanding. Accepted frames become sRGB BGRA8 with a 1280-pixel maximum long edge. Packed rows use overflow-safe capacity checks. The native client maps only a regular, private, same-user file, opened with O_NOFOLLOW; the engine provides its absolute path and 32 MiB capacity.

The producer writes a complete frame and sends only sequence, width, height, bytes_per_row and timestamp_s over the Unix socket. The engine copies rows into private memory before inference. The gate releases after the response, with no pending-frame array. The displayed CGImage owns the accepted byte snapshot, so another mmap write cannot alter it beneath old detections.

Stop closes the gate first, detaches/stops the source, and sends the independent stop request. The engine discards outstanding inference before persistence. Mapping writes and closure share a lock; an outstanding HTTP task cannot publish after stop. Project navigation, leaving Run, native errors, EOF, retention limits, and application termination stop the session. A generation token rejects late replies. Quit waits for capture cleanup and annotation saves.

## Verification

Native self-tests include actual temporary-file mmap writes, frame layout, sampling, sequence, busy-drop and stop-state checks. They do not simulate or claim camera capture.

A real recorded-media check uses the actual AVAssetReader and publisher without capture permission:

```sh
app/.build/debug/VisionApp --replay-video /absolute/video.mp4 \
  --project PROJECT_ID --socket /private/engine.sock --preview-only --duration 30 \
  --output-dir /absolute/probe-output
```

The optional output directory retains native frame PNGs, result overlays and result JSON for coordinate inspection. Omit preview-only only for an explicitly approved deployment. This mode never imports the clip into the dataset. Camera and screen permission paths require interactive macOS validation.

References: [Apple capture output](https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput/setsamplebufferdelegate(_:queue:)), [ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit), [AVAssetReader output](https://developer.apple.com/documentation/avfoundation/avassetreaderoutput). macOS 15 deployment target.

Real replay verification on 2026-10-28: the native AVAssetReader path processed 11 frames from NVIDIA Warehouse026 Camera_0000 in a 15-second probe. First OWLv2 inference took 5.94 seconds; subsequent responses took 0.70–0.96 seconds. The engine retained zero evidence frames and zero events, and no deployment was approved. `artifacts/native-live-probe/` contains original OpenCV frame 0, native BGRA-derived PNGs, actual detection overlays, result JSON and logs. Upright RGB mean absolute difference from independently decoded/resized frame 0 was 8.89, versus 45.64 for a vertical flip; root visually confirmed the person box aligns. These are transport/inference/coordinate checks, not accuracy evaluation.
