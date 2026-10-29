import AppKit

enum ReplayArtifacts {
    static func save(image: CGImage, response: LiveFrameResponse, directory: URL) throws {
        let stem = String(format: "%04d", response.processedFrames)
        try writePNG(image, to: directory.appendingPathComponent("frame-\(stem).png"))
        try JSONEncoder().encode(response.result).write(to: directory.appendingPathComponent("result-\(stem).json"))
        guard let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                                      bytesPerRow: image.width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
            throw EngineError.protocolError("Cannot allocate replay overlay.")
        }
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        context.setStrokeColor(CGColor(red: 0.3, green: 1, blue: 0.7, alpha: 1)); context.setLineWidth(2)
        for detection in response.result.detections where detection.box.count == 4 {
            let b = detection.box
            // Engine boxes use top-left normalized coordinates; CGContext is bottom-left.
            context.stroke(CGRect(x: b[0] * Double(image.width), y: (1 - b[3]) * Double(image.height),
                                  width: (b[2] - b[0]) * Double(image.width), height: (b[3] - b[1]) * Double(image.height)))
        }
        if let overlay = context.makeImage() { try writePNG(overlay, to: directory.appendingPathComponent("overlay-\(stem).png")) }
    }
    private static func writePNG(_ image: CGImage, to url: URL) throws {
        guard let data = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else { throw EngineError.protocolError("PNG encoding failed.") }
        try data.write(to: url)
    }
}
