import Foundation
import CryptoKit

enum TextRegionPredictionCopy {
    static func hasSourceIdentity(_ hash: String?) -> Bool {
        guard let hash else { return false }
        return hash.utf8.count == 64 && hash.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    static func verifiedImageHash(preview: String?, current: String) throws -> String {
        guard let preview, hasSourceIdentity(preview) else {
            throw EngineError.protocolError("This preview has no verified image identity. Run a new preview before copying a prediction.")
        }
        guard preview == current else {
            throw EngineError.protocolError("The image changed after this preview. Run a new preview before copying a prediction.")
        }
        return preview
    }
    static func region(block: FrameInference, index: Int, imageSHA256: String, id: String = UUID().uuidString.lowercased(), createdAt: String = ISO8601DateFormatter().string(from: Date())) throws -> TextRegion {
        guard ["ocr", "barcode"].contains(block.result.task), block.result.readings.indices.contains(index) else {
            throw EngineError.protocolError("Select an OCR or barcode observation to copy into a text region.")
        }
        let original = block.result.readings[index]
        let mapped = ReadingGeometry.mapped(original, transform: block.inputToFrame)
        guard let polygon = mapped.polygon, TextRegionGeometry.valid(polygon), let box = ReadingGeometry.envelope(polygon) else {
            throw EngineError.protocolError("This observation has no valid four-corner geometry. Draw a region manually instead.")
        }
        let identity = block.result.identity
        let seed = TextRegionSeed(modelID: identity.modelID, adapterID: identity.adapterID, identityHash: identity.identityHash,
                                  blockID: block.blockID, observationIndex: index, observation: original,
                                  inputToFrame: block.inputToFrame, imageSHA256: imageSHA256, createdAt: createdAt)
        return TextRegion(id: id, polygon: polygon, box: box, transcript: original.text, seed: seed)
    }
    static func imageHash(_ path: String) throws -> String {
        let handle = try FileHandle(forReadingFrom: URL(fileURLWithPath: path)); defer { try? handle.close() }
        var hash = SHA256()
        while let bytes = try handle.read(upToCount: 1024*1024), !bytes.isEmpty { hash.update(data: bytes) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

extension DatasetWorkspace {
    func copyReading(block: FrameInference, index: Int, sourceImageSHA256: String?) {
        guard let annotation, let image = activeImage, !hasConflict, !loading else { return }
        do {
            let hash = try TextRegionPredictionCopy.verifiedImageHash(preview: sourceImageSHA256, current: TextRegionPredictionCopy.imageHash(image.imagePath))
            let region = try TextRegionPredictionCopy.region(block: block, index: index, imageSHA256: hash)
            if let issue = TextRegionEditing.validationError(annotation.textRegions + [region]) { error = issue; return }
            change(TextRegionEditing.replacing(annotation, regions: annotation.textRegions + [region]))
            chooseLabelMode(.textRegions); selectedTextRegionID = region.id
            notice = "Prediction copied as an unreviewed text region. Check the transcript and geometry against the image."
        } catch { self.error = error.localizedDescription }
    }
}
