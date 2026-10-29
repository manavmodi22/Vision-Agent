import AppKit

enum AnnotationTool: String, CaseIterable { case select, box, pan }
enum BoxHandle: Int, CaseIterable {
    case topLeft, top, topRight, right, bottomRight, bottom, bottomLeft, left
    var point: CGPoint {
        switch self {
        case .topLeft: return CGPoint(x: 0, y: 0)
        case .top: return CGPoint(x: 0.5, y: 0)
        case .topRight: return CGPoint(x: 1, y: 0)
        case .right: return CGPoint(x: 1, y: 0.5)
        case .bottomRight: return CGPoint(x: 1, y: 1)
        case .bottom: return CGPoint(x: 0.5, y: 1)
        case .bottomLeft: return CGPoint(x: 0, y: 1)
        case .left: return CGPoint(x: 0, y: 0.5)
        }
    }
}
enum AnnotationGeometry {
    static let minimumSize = 0.001
    static func imageRect(image: CGSize, viewport: CGSize, zoom: CGFloat, pan: CGPoint) -> CGRect {
        let fitted = ImageGeometry.fittedRect(image: image, container: viewport)
        let size = CGSize(width: fitted.width * zoom, height: fitted.height * zoom)
        return CGRect(x: (viewport.width-size.width)/2+pan.x, y: (viewport.height-size.height)/2+pan.y, width: size.width, height: size.height)
    }
    static func boxRect(_ box: [Double], image: CGRect) -> CGRect {
        guard box.count == 4 else { return .zero }
        return CGRect(x: image.minX+box[0]*image.width, y: image.minY+box[1]*image.height,
                      width: (box[2]-box[0])*image.width, height: (box[3]-box[1])*image.height)
    }
    static func point(_ point: CGPoint, image: CGRect) -> CGPoint {
        CGPoint(x: max(0, min(1, (point.x-image.minX)/image.width)), y: max(0, min(1, (point.y-image.minY)/image.height)))
    }
    static func move(_ box: [Double], dx: Double, dy: Double) -> [Double] {
        guard box.count == 4 else { return box }
        let x = max(-box[0], min(1-box[2], dx)), y = max(-box[1], min(1-box[3], dy))
        return [box[0]+x, box[1]+y, box[2]+x, box[3]+y]
    }
    static func resize(_ box: [Double], handle: BoxHandle, dx: Double, dy: Double) -> [Double] {
        guard box.count == 4 else { return box }
        var value = box
        if handle.point.x == 0 { value[0] = max(0, min(box[2]-minimumSize, box[0]+dx)) }
        if handle.point.x == 1 { value[2] = min(1, max(box[0]+minimumSize, box[2]+dx)) }
        if handle.point.y == 0 { value[1] = max(0, min(box[3]-minimumSize, box[1]+dy)) }
        if handle.point.y == 1 { value[3] = min(1, max(box[1]+minimumSize, box[3]+dy)) }
        return value
    }
    static func handle(at point: CGPoint, box: CGRect) -> BoxHandle? {
        BoxHandle.allCases.first { handle in
            let center = CGPoint(x: box.minX+handle.point.x*box.width, y: box.minY+handle.point.y*box.height)
            return abs(center.x-point.x) <= 7 && abs(center.y-point.y) <= 7
        }
    }
}
extension NSColor {
    convenience init(hex: String) {
        let value = UInt64(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0x5BD6C0
        self.init(srgbRed: Double((value >> 16) & 255)/255, green: Double((value >> 8) & 255)/255, blue: Double(value & 255)/255, alpha: 1)
    }
}
