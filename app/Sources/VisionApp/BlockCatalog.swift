import Foundation

struct BlockDefinition: Codable, Identifiable {
    var type: String
    var description: String
    var params: JSONValue
    var inputs: [String: String]
    var outputs: [String: String]
    var id: String { type }
    var properties: [String: JSONValue] { params.object["properties"]?.object ?? [:] }
    var required: [String] { if case .array(let values) = params.object["required"] { return values.compactMap(\.string) }; return [] }
    func initialParams(classes: [String]) -> [String: JSONValue] {
        var result: [String: JSONValue] = [:]
        for (key, schema) in properties {
            if let value = schema.object["default"] { result[key] = value }
            else if required.contains(key) { result[key] = placeholder(key) }
        }
        if type == "detect" || type == "detect_open_vocab" { result["classes"] = .array(classes.map(JSONValue.string)) }
        return result
    }
    func placeholder(_ key: String) -> JSONValue {
        let schema = properties[key]?.object ?? [:]
        if let value = schema["default"] { return value }
        switch schema["type"]?.string {
        case "array": return .array([])
        case "integer", "number": return .number(0)
        case "boolean": return .bool(false)
        case "object": return .object([:])
        default: return .string("")
        }
    }
}
struct BlockPortChoice: Identifiable, Equatable {
    var reference: String
    var type: String
    var id: String { reference }
}
enum BlockGraphEditing {
    static func compatibleSources(pipeline: Pipeline, blockIndex: Int, input: String, catalog: [BlockDefinition]) -> [BlockPortChoice] {
        guard pipeline.blocks.indices.contains(blockIndex), let definition = catalog.first(where: { $0.type == pipeline.blocks[blockIndex].type }), let expected = definition.inputs[input] else { return [] }
        var choices: [BlockPortChoice] = expected == "frames" ? [BlockPortChoice(reference: "$inputs.source", type: "frames")] : []
        for block in pipeline.blocks.prefix(blockIndex) {
            guard let schema = catalog.first(where: { $0.type == block.type }) else { continue }
            for output in schema.outputs.keys.sorted() where schema.outputs[output] == expected {
                choices.append(BlockPortChoice(reference: "$\(block.id).\(output)", type: expected))
            }
        }
        return choices
    }
    static func uniqueID(type: String, blocks: [PipelineBlock]) -> String {
        let existing = Set(blocks.map(\.id))
        if !existing.contains(type) { return type }
        var number = 2
        while existing.contains("\(type)_\(number)") { number += 1 }
        return "\(type)_\(number)"
    }
}
