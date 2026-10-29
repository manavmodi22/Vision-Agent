import AppKit

enum AnnotationLabelMode: String, CaseIterable { case objects = "Object boxes", textRegions = "Text regions" }

enum TextRegionGeometry {
    static func valid(_ polygon: [[Double]]) -> Bool {
        guard polygon.count == 4, polygon.allSatisfy({ $0.count == 2 && $0.allSatisfy { $0.isFinite && (0...1).contains($0) } }) else { return false }
        var signs: [Double] = []
        for index in polygon.indices {
            let a = polygon[index], b = polygon[(index+1)%4], c = polygon[(index+2)%4]
            let cross = (b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0])
            guard abs(cross) > 1e-8 else { return false }
            signs.append(cross)
        }
        return (signs.allSatisfy { $0 > 0 } || signs.allSatisfy { $0 < 0 }) && ReadingGeometry.envelope(polygon) != nil
    }
    static func rectangle(_ box: [Double]) -> [[Double]] {
        guard box.count == 4 else { return [] }
        return [[box[0],box[1]], [box[2],box[1]], [box[2],box[3]], [box[0],box[3]]]
    }
    static func move(_ polygon: [[Double]], dx: Double, dy: Double) -> [[Double]] {
        guard valid(polygon), let box = ReadingGeometry.envelope(polygon) else { return polygon }
        let x = max(-box[0], min(1-box[2], dx)), y = max(-box[1], min(1-box[3], dy))
        let result = polygon.map { [max(0, min(1, $0[0]+x)), max(0, min(1, $0[1]+y))] }
        return valid(result) ? result : polygon
    }
    static func moveCorner(_ polygon: [[Double]], index: Int, dx: Double, dy: Double) -> [[Double]] {
        guard valid(polygon), polygon.indices.contains(index) else { return polygon }
        var result = polygon
        result[index] = [max(0, min(1, polygon[index][0]+dx)), max(0, min(1, polygon[index][1]+dy))]
        return valid(result) ? result : polygon
    }
    static func screenPoint(_ point: [Double], rect: CGRect) -> CGPoint {
        CGPoint(x: rect.minX+point[0]*rect.width, y: rect.minY+point[1]*rect.height)
    }
    static func path(_ polygon: [[Double]], rect: CGRect) -> NSBezierPath {
        let path = NSBezierPath()
        guard valid(polygon) else { return path }
        for (index, point) in polygon.enumerated() {
            let p = screenPoint(point, rect: rect)
            if index == 0 { path.move(to: p) } else { path.line(to: p) }
        }
        path.close(); return path
    }
    static func corner(at point: CGPoint, polygon: [[Double]], rect: CGRect) -> Int? {
        guard valid(polygon) else { return nil }
        return polygon.indices.first { index in
            let p = screenPoint(polygon[index], rect: rect)
            return abs(point.x-p.x) <= 8 && abs(point.y-p.y) <= 8
        }
    }
}
