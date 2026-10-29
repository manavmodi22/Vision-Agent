import SwiftUI
import AppKit

struct AnnotationCanvas: NSViewRepresentable {
    let imagePath: String
    let detections: [Detection]
    let predictions: [Detection]
    let colors: [String: String]
    let selectedIndex: Int?
    let tool: AnnotationTool
    let zoom: Double
    let fitToken: Int
    let onSelect: (Int?) -> Void
    let onCreate: ([Double]) -> Void
    let onEdit: ([Detection]) -> Void
    let onCommand: (String) -> Void
    let onZoom: (Double) -> Void
    var readings: [DisplayReading] = []
    var selectedReadingID: String? = nil
    func makeNSView(context: Context) -> AnnotationCanvasView { AnnotationCanvasView() }
    func updateNSView(_ view: AnnotationCanvasView, context: Context) {
        view.configure(self)
    }
}

final class AnnotationCanvasView: NSView {
    enum Gesture {
        case none, create(CGPoint), move(Int, CGPoint, [Double]), resize(Int, BoxHandle, CGPoint, [Double]), pan(CGPoint, CGPoint)
    }
    private var image: NSImage?
    private var imagePath = ""
    private var boxes: [Detection] = []
    private var predictions: [Detection] = []
    private var readings: [DisplayReading] = []
    private var selectedReadingID: String?
    private var colors: [String: String] = [:]
    private var selectedIndex: Int?
    private var tool: AnnotationTool = .select
    private var zoom: Double = 1
    private var pan = CGPoint.zero
    private var fitToken = 0
    private var gesture = Gesture.none
    private var newBox: [Double]?
    private var spaceHeld = false
    private var onSelect: (Int?) -> Void = { _ in }
    private var onCreate: ([Double]) -> Void = { _ in }
    private var onEdit: ([Detection]) -> Void = { _ in }
    private var onCommand: (String) -> Void = { _ in }
    private var onZoom: (Double) -> Void = { _ in }
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    private var imageRect: CGRect { AnnotationGeometry.imageRect(image: image?.size ?? .zero, viewport: bounds.size, zoom: zoom, pan: pan) }
    func configure(_ input: AnnotationCanvas) {
        if imagePath != input.imagePath {
            imagePath = input.imagePath; image = NSImage(contentsOfFile: imagePath)
            pan = .zero; zoom = 1; gesture = .none; newBox = nil
        }
        if input.fitToken != fitToken { fitToken = input.fitToken; pan = .zero; zoom = 1 }
        boxes = input.detections; predictions = input.predictions; colors = input.colors
        readings = input.readings; selectedReadingID = input.selectedReadingID
        selectedIndex = input.selectedIndex; tool = input.tool; zoom = input.zoom
        onSelect = input.onSelect; onCreate = input.onCreate; onEdit = input.onEdit
        onCommand = input.onCommand; onZoom = input.onZoom
        needsDisplay = true; window?.invalidateCursorRects(for: self)
    }
    override func resetCursorRects() {
        addCursorRect(bounds, cursor: spaceHeld || tool == .pan ? .openHand : tool == .box ? .crosshair : .arrow)
    }
    override func draw(_ dirtyRect: NSRect) {
        NSColor(hex: "101419").setFill(); bounds.fill()
        guard let image else {
            let text = "Image could not be loaded" as NSString
            text.draw(at: CGPoint(x: 20, y: 20), withAttributes: [.foregroundColor: NSColor.secondaryLabelColor, .font: NSFont.systemFont(ofSize: 13)])
            return
        }
        let rect = imageRect
        NSGraphicsContext.current?.imageInterpolation = .high
        image.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 1, respectFlipped: true, hints: nil)
        for prediction in predictions { drawBox(prediction, rect: rect, selected: false, prediction: true) }
        for (index, detection) in boxes.enumerated() { drawBox(detection, rect: rect, selected: index == selectedIndex, prediction: false) }
        drawReadings(rect: rect)
        if let box = newBox {
            let draft = AnnotationGeometry.boxRect(box, image: rect)
            NSColor(hex: "5BD6C0").withAlphaComponent(0.15).setFill(); draft.fill()
            NSColor(hex: "5BD6C0").setStroke(); let outline = NSBezierPath(rect: draft); outline.lineWidth = 1.5; outline.stroke()
        }
    }
    private func drawReadings(rect: CGRect) {
        for reading in readings {
            guard let points = reading.observation.polygon, let box = reading.observation.box else { continue }
            let path = NSBezierPath()
            for (index, p) in points.enumerated() {
                let point = CGPoint(x: rect.minX+p[0]*rect.width, y: rect.minY+p[1]*rect.height)
                if index == 0 { path.move(to: point) } else { path.line(to: point) }
            }
            path.close(); path.setLineDash([5, 3], count: 2, phase: 0)
            let selected = selectedReadingID == reading.id
            path.lineWidth = selected ? 3 : 1.5
            let color = selected ? NSColor.systemYellow : NSColor.systemCyan
            color.setStroke(); path.stroke()
            let label = "\(reading.index+1)" as NSString
            label.draw(at: CGPoint(x: rect.minX+box[0]*rect.width, y: max(rect.minY, rect.minY+box[1]*rect.height-16)),
                       withAttributes: [.foregroundColor: color, .backgroundColor: NSColor.black, .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .semibold)])
        }
    }
    private func drawBox(_ detection: Detection, rect: CGRect, selected: Bool, prediction: Bool) {
        let box = AnnotationGeometry.boxRect(detection.box, image: rect)
        let color = prediction ? NSColor.systemOrange : NSColor(hex: colors[detection.label] ?? "5BD6C0")
        let outline = NSBezierPath(rect: box)
        outline.lineWidth = selected ? 2 : 1.4
        if prediction { outline.setLineDash([5, 4], count: 2, phase: 0) }
        color.withAlphaComponent(prediction ? 0.75 : 1).setStroke(); outline.stroke()
        if selected { color.withAlphaComponent(0.08).setFill(); box.fill() }
        let title = (prediction ? "prediction · " : "") + detection.label + (prediction ? String(format: " %.0f%%", detection.confidence*100) : "")
        let font = NSFont.monospacedSystemFont(ofSize: 11, weight: .medium)
        let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.black]
        let size = (title as NSString).size(withAttributes: attributes)
        let label = CGRect(x: box.minX, y: max(rect.minY, box.minY-21), width: size.width+10, height: 20)
        color.withAlphaComponent(prediction ? 0.8 : 1).setFill(); label.fill()
        (title as NSString).draw(at: CGPoint(x: label.minX+5, y: label.minY+3), withAttributes: attributes)
        if selected {
            for handle in BoxHandle.allCases {
                let center = CGPoint(x: box.minX+handle.point.x*box.width, y: box.minY+handle.point.y*box.height)
                let square = CGRect(x: center.x-4, y: center.y-4, width: 8, height: 8)
                NSColor.white.setFill(); square.fill(); color.setStroke(); NSBezierPath(rect: square).stroke()
            }
        }
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        let point = convert(event.locationInWindow, from: nil)
        guard image != nil else { return }
        if spaceHeld || tool == .pan || event.modifierFlags.contains(.option) { gesture = .pan(point, pan); NSCursor.closedHand.set(); return }
        let rect = imageRect
        if tool == .box {
            guard rect.contains(point) else { return }
            gesture = .create(AnnotationGeometry.point(point, image: rect)); newBox = nil; return
        }
        if let index = selectedIndex, boxes.indices.contains(index), let handle = AnnotationGeometry.handle(at: point, box: AnnotationGeometry.boxRect(boxes[index].box, image: rect)) {
            gesture = .resize(index, handle, point, boxes[index].box); return
        }
        let selected = boxes.indices.reversed().first { AnnotationGeometry.boxRect(boxes[$0].box, image: rect).contains(point) }
        selectedIndex = selected; onSelect(selected)
        if let index = selected { gesture = .move(index, point, boxes[index].box) } else { gesture = .none }
        needsDisplay = true
    }
    override func mouseDragged(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        let rect = imageRect
        switch gesture {
        case .none: break
        case .pan(let origin, let initial): pan = CGPoint(x: initial.x+point.x-origin.x, y: initial.y+point.y-origin.y)
        case .create(let start):
            let end = AnnotationGeometry.point(point, image: rect)
            newBox = [min(start.x,end.x), min(start.y,end.y), max(start.x,end.x), max(start.y,end.y)]
        case .move(let index, let start, let original):
            guard boxes.indices.contains(index) else { return }
            boxes[index].box = AnnotationGeometry.move(original, dx: (point.x-start.x)/rect.width, dy: (point.y-start.y)/rect.height)
        case .resize(let index, let handle, let start, let original):
            guard boxes.indices.contains(index) else { return }
            boxes[index].box = AnnotationGeometry.resize(original, handle: handle, dx: (point.x-start.x)/rect.width, dy: (point.y-start.y)/rect.height)
        }
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        switch gesture {
        case .create:
            if let box = newBox, box[2]-box[0] >= AnnotationGeometry.minimumSize, box[3]-box[1] >= AnnotationGeometry.minimumSize { onCreate(box) }
        case .move, .resize: onEdit(boxes)
        case .none, .pan: break
        }
        gesture = .none; newBox = nil; needsDisplay = true; window?.invalidateCursorRects(for: self)
    }
    override func rightMouseDown(with event: NSEvent) { window?.makeFirstResponder(self); gesture = .pan(convert(event.locationInWindow, from: nil), pan) }
    override func rightMouseDragged(with event: NSEvent) { mouseDragged(with: event) }
    override func rightMouseUp(with event: NSEvent) { mouseUp(with: event) }
    override func scrollWheel(with event: NSEvent) {
        if event.modifierFlags.contains(.option) || event.modifierFlags.contains(.command) {
            setZoom(zoom * exp(event.scrollingDeltaY*0.02), anchor: convert(event.locationInWindow, from: nil))
        } else { pan.x -= event.scrollingDeltaX; pan.y -= event.scrollingDeltaY; needsDisplay = true }
    }
    override func magnify(with event: NSEvent) { setZoom(zoom * (1+event.magnification), anchor: convert(event.locationInWindow, from: nil)) }
    private func setZoom(_ value: Double, anchor: CGPoint) {
        let old = imageRect
        guard old.width > 0, old.height > 0 else { return }
        let x = (anchor.x-old.minX)/old.width, y = (anchor.y-old.minY)/old.height
        zoom = max(0.25, min(12, value))
        let updated = imageRect
        pan.x += anchor.x-(updated.minX+x*updated.width); pan.y += anchor.y-(updated.minY+y*updated.height)
        onZoom(zoom); needsDisplay = true
    }
    override func keyDown(with event: NSEvent) {
        let key = event.charactersIgnoringModifiers?.lowercased() ?? ""
        if key == " " { spaceHeld = true; window?.invalidateCursorRects(for: self); return }
        if event.modifierFlags.contains(.command), key == "z" { onCommand(event.modifierFlags.contains(.shift) ? "redo" : "undo"); return }
        if event.keyCode == 51 || event.keyCode == 117 { onCommand("delete"); return }
        if event.keyCode == 123 { onCommand("previous"); return }
        if event.keyCode == 124 { onCommand("next"); return }
        if event.keyCode == 53 { gesture = .none; newBox = nil; onCommand("cancel"); needsDisplay = true; return }
        if ["v", "b", "h", "f", "+", "=", "-"].contains(key) { onCommand(key); return }
        super.keyDown(with: event)
    }
    override func keyUp(with event: NSEvent) {
        if event.charactersIgnoringModifiers == " " { spaceHeld = false; window?.invalidateCursorRects(for: self) } else { super.keyUp(with: event) }
    }
}
