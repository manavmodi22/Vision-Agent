import Foundation

enum TextRegionEditing {
    static func validationError(_ regions: [TextRegion]) -> String? {
        if regions.count > 2000 { return "An image supports up to 2,000 text regions." }
        if Set(regions.map(\.id)).count != regions.count { return "Text-region identifiers must be unique." }
        if !regions.allSatisfy({ TextRegionGeometry.valid($0.polygon) }) { return "Text regions need four distinct convex corners inside the image." }
        if regions.contains(where: { ($0.transcript?.unicodeScalars.count ?? 0) > 16384 }) { return "A transcript supports up to 16,384 Unicode characters." }
        if regions.reduce(0, { $0+($1.transcript?.utf8.count ?? 0) }) > 1024*1024 { return "Text-region transcripts exceed 1 MiB for this image." }
        return nil
    }
    static func projection(_ regions: [TextRegion]) -> [String] {
        regions.compactMap(\.transcript)
    }
    static func isComplete(_ annotation: Annotation) -> Bool {
        annotation.textRegions.allSatisfy { TextRegionGeometry.valid($0.polygon) && $0.transcript?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false }
    }
    static func projected(_ annotation: Annotation) -> Annotation {
        var updated = annotation
        if updated.expectedTextSource == "regions" { updated.expectedTexts = projection(updated.textRegions) }
        return updated
    }
    static func replacing(_ annotation: Annotation, regions: [TextRegion]) -> Annotation {
        guard annotation.textRegions != regions else { return annotation }
        var updated = annotation; updated.textRegions = regions; updated.reviewed = false
        return projected(updated)
    }
    static func restoring(_ target: Annotation, from current: Annotation) -> Annotation {
        var restored = target
        if target.textRegions != current.textRegions || target.detections != current.detections ||
            target.expectedTextSource != current.expectedTextSource || target.expectedTexts.map({ Data($0.utf8) }) != current.expectedTexts.map({ Data($0.utf8) }) {
            restored.reviewed = false
        }
        return projected(restored)
    }
}

extension DatasetWorkspace {
    func createTextRegion(_ box: [Double]) {
        guard let annotation else { return }
        let polygon = TextRegionGeometry.rectangle(box)
        guard TextRegionGeometry.valid(polygon) else { error = "Draw a nonempty text region inside the image."; return }
        let region = TextRegion(id: UUID().uuidString.lowercased(), polygon: polygon, box: box, transcript: nil, seed: nil)
        if let issue = TextRegionEditing.validationError(annotation.textRegions + [region]) { error = issue; return }
        change(TextRegionEditing.replacing(annotation, regions: annotation.textRegions + [region]))
        selectedTextRegionID = region.id; tool = .select
    }
    func editTextRegions(_ regions: [TextRegion]) {
        guard let annotation else { return }
        if let issue = TextRegionEditing.validationError(regions) { error = issue; return }
        change(TextRegionEditing.replacing(annotation, regions: regions))
    }
    func editTranscript(id: String, value: String) {
        guard let annotation, let index = annotation.textRegions.firstIndex(where: { $0.id == id }) else { return }
        var regions = annotation.textRegions; regions[index].transcript = value.isEmpty ? nil : value
        editTextRegions(regions)
    }
    func deleteTextRegion() {
        guard let annotation, let id = selectedTextRegionID else { return }
        editTextRegions(annotation.textRegions.filter { $0.id != id }); selectedTextRegionID = nil
    }
    func setExpectedTextSource(_ source: String) {
        guard var annotation, ["manual", "regions"].contains(source), source != annotation.expectedTextSource else { return }
        guard source != "regions" || TextRegionEditing.isComplete(annotation) else { error = "Complete every transcript before using region values."; return }
        annotation.expectedTextSource = source; annotation.reviewed = false; change(annotation)
    }
}
