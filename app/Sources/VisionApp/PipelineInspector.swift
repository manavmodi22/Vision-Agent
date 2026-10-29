import SwiftUI

struct CandidateUpdateRequest: Encodable {
    var spec: Pipeline
    var baseSpec: Pipeline
    enum CodingKeys: String, CodingKey { case spec, baseSpec = "base_spec" }
}

struct PipelineInspector: View {
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<Pipeline?> private var draft: Pipeline?
    @NativeState<Pipeline?> private var baseline: Pipeline?
    @NativeState<Int> private var loadedCandidateIndex = 0
    @NativeState<String?> private var selectedBlock: String?
    @NativeState<String> private var jsonDraft = ""
    @NativeState<String?> private var jsonError: String?
    @NativeState<[BlockDefinition]> private var catalog: [BlockDefinition] = []
    @NativeState<String?> private var catalogError: String?
    private var dirty: Bool { draft != nil && draft != baseline }
    private var blockIndex: Int? { draft?.blocks.firstIndex { $0.id == selectedBlock } }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Workflow blocks").font(.headline)
                if dirty { Text("Unsaved changes").font(.caption).foregroundStyle(.orange) }
                Spacer()
                Menu {
                    ForEach(catalog) { definition in Button(definition.type.replacingOccurrences(of: "_", with: " ")) { addBlock(definition) }.help(definition.description) }
                } label: { Label("Add block", systemImage: "plus") }.fixedSize().disabled(draft == nil || catalog.isEmpty || model.busy || (draft?.blocks.count ?? 0) >= 64)
                Button("Revert") { reset() }.disabled(!dirty || model.busy)
                Button("Validate & save") {
                    if let draft, let baseline {
                        let index = loadedCandidateIndex
                        model.saveCandidate(draft, base: baseline) { saved in
                            guard loadedCandidateIndex == index, model.selectedCandidate == index else { return }
                            self.baseline = saved
                            if self.draft == draft { self.draft = saved; resetJSON() }
                        }
                    }
                }.buttonStyle(.borderedProminent).disabled(!dirty || model.busy || jsonError != nil)
            }
            if let catalogError { Text(catalogError).font(.caption).foregroundStyle(.orange) }
            if let pipeline = draft {
                HStack(spacing: 12) {
                    TextField("Workflow name", text: Binding(get: { draft?.name ?? "" }, set: { draft?.name = $0 })).textFieldStyle(.roundedBorder)
                    Picker("Metric", selection: Binding(get: { draft?.evaluation?.object["metric"]?.string ?? "count_mae" }, set: { setEvaluation("metric", .string($0)) })) {
                        Text("Count MAE").tag("count_mae"); Text("Precision").tag("precision"); Text("Recall").tag("recall"); Text("Text accuracy").tag("text_accuracy")
                    }.frame(width: 200)
                    TextField("Target", value: Binding(get: { if case .number(let value) = draft?.evaluation?.object["target"] { return value }; return 0.5 }, set: { setEvaluation("target", .number($0)) }), format: .number.grouping(.never)).textFieldStyle(.roundedBorder).frame(width: 65)
                }
                HStack(alignment: .top, spacing: 16) {
                    VStack(spacing: 4) {
                        ForEach(Array(pipeline.blocks.enumerated()), id: \.element.id) { index, block in
                            Button { selectedBlock = block.id; resetJSON() } label: {
                                HStack { Text(String(format: "%02d", index+1)).font(.caption.monospaced()).foregroundStyle(Studio.muted); VStack(alignment: .leading, spacing: 3) { Text(block.type.replacingOccurrences(of: "_", with: " ")).font(.system(size: 12, weight: .medium)); Text(block.id).font(.system(size: 10, design: .monospaced)).foregroundStyle(Studio.muted) }; Spacer() }.padding(10).background(selectedBlock == block.id ? Studio.raised : .clear).clipShape(RoundedRectangle(cornerRadius: 6))
                            }.buttonStyle(.plain)
                        }
                    }.frame(width: 180)
                    Divider()
                    VStack(alignment: .leading, spacing: 13) {
                        if let index = blockIndex, let block = draft?.blocks[index] {
                            HStack {
                                Text(block.type.replacingOccurrences(of: "_", with: " ").capitalized).font(.headline); Spacer()
                                Button { moveBlock(index, offset: -1) } label: { Image(systemName: "arrow.up") }.disabled(index == 0)
                                Button { moveBlock(index, offset: 1) } label: { Image(systemName: "arrow.down") }.disabled(index == (draft?.blocks.count ?? 0)-1)
                                Button { removeBlock(index) } label: { Image(systemName: "trash") }.disabled((draft?.blocks.count ?? 0) <= 1).help("Remove this block; reconnect downstream inputs before saving")
                            }
                            Text(catalog.first(where: { $0.type == block.type })?.description ?? block.id).font(.caption).foregroundStyle(Studio.muted)
                            ForEach(parameterKeys(block), id: \.self) { key in
                                parameter(key, value: block.params?[key] ?? catalog.first(where: { $0.type == block.type })?.placeholder(key) ?? .null, index: index)
                            }
                            if (block.params ?? [:]).isEmpty { Text("This block has no parameters.").font(.caption).foregroundStyle(Studio.muted) }
                            Divider()
                            Text("Connections").font(.caption.weight(.semibold))
                            ForEach(inputKeys(block), id: \.self) { key in connectionPicker(key, index: index) }
                            Text("Choices are upstream outputs with the matching type. Move a block above this one to use its output.").font(.caption).foregroundStyle(Studio.muted)
                            DisclosureGroup("Advanced parameters JSON") {
                                TextEditor(text: $jsonDraft).font(.system(size: 11, design: .monospaced)).frame(height: 130).scrollContentBackground(.hidden).padding(6).background(Studio.background)
                                Button("Apply parameters") { applyJSON(index: index) }.font(.caption)
                                if let jsonError { Text(jsonError).font(.caption).foregroundStyle(.orange) }
                            }.font(.caption)
                        } else { Text("Select a block to edit its parameters and connections.").font(.callout).foregroundStyle(Studio.muted) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("Saved edits invalidate previous evaluation and deployment approval. The engine checks types, model availability and graph connections.").font(.caption).foregroundStyle(Studio.muted)
            } else { Text("Build a workflow from your dataset classes or a task description to start editing blocks.").font(.callout).foregroundStyle(Studio.muted) }
        }.panel().onAppear { reset() }.onChange(of: model.candidate) { _, candidate in
            if loadedCandidateIndex != model.selectedCandidate || (!dirty && baseline != candidate) { reset() }
        }
            .task {
                do { catalog = try await model.client.request("GET", "/blocks") }
                catch { catalogError = "Block catalog unavailable: \(error.localizedDescription)" }
            }
    }
    @ViewBuilder
    private func parameter(_ key: String, value: JSONValue, index: Int) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(key.replacingOccurrences(of: "_", with: " ").capitalized).font(.caption).foregroundStyle(Studio.muted)
            switch value {
            case .string:
                TextField(key == "when" ? "count >= 12" : key, text: Binding(get: { draft?.blocks[index].params?[key]?.string ?? value.string ?? "" }, set: { draft?.blocks[index].params?[key] = .string($0); resetJSON() })).textFieldStyle(.roundedBorder)
            case .number(let number):
                TextField(key, value: Binding(get: { if case .number(let v) = draft?.blocks[index].params?[key] { return v }; return number }, set: { draft?.blocks[index].params?[key] = .number($0); resetJSON() }), format: .number.grouping(.never)).textFieldStyle(.roundedBorder)
            case .bool(let flag):
                Toggle("Enabled", isOn: Binding(get: { if case .bool(let v) = draft?.blocks[index].params?[key] { return v }; return flag }, set: { draft?.blocks[index].params?[key] = .bool($0); resetJSON() })).toggleStyle(.checkbox)
            case .array(let values) where values.allSatisfy({ $0.string != nil }) && (!values.isEmpty || ["classes", "languages", "labels"].contains(key)):
                TextField("Comma-separated values", text: Binding(get: { if case .array(let v) = draft?.blocks[index].params?[key] { return v.compactMap(\.string).joined(separator: ", ") }; return values.compactMap(\.string).joined(separator: ", ") }, set: { draft?.blocks[index].params?[key] = .array($0.split(separator: ",").map { .string($0.trimmingCharacters(in: .whitespaces)) }.filter { $0.string?.isEmpty == false }); resetJSON() })).textFieldStyle(.roundedBorder)
            default: Text("Edit structured values in Advanced parameters JSON.").font(.caption).foregroundStyle(Studio.muted)
            }
        }
    }
    private func reset() {
        baseline = model.candidate; loadedCandidateIndex = model.selectedCandidate
        draft = model.candidate
        if let count = draft?.blocks.count { for index in 0..<count { if draft?.blocks[index].params == nil { draft?.blocks[index].params = [:] }; if draft?.blocks[index].connections == nil { draft?.blocks[index].connections = [:] } } }
        selectedBlock = draft?.blocks.first?.id; jsonError = nil; resetJSON()
    }
    private func parameterKeys(_ block: PipelineBlock) -> [String] {
        Array(Set((block.params ?? [:]).keys).union(catalog.first(where: { $0.type == block.type })?.properties.keys.map { $0 } ?? [])).sorted()
    }
    private func inputKeys(_ block: PipelineBlock) -> [String] {
        Array(Set((block.connections ?? [:]).keys).union(catalog.first(where: { $0.type == block.type })?.inputs.keys.map { $0 } ?? [])).sorted()
    }
    private func setEvaluation(_ key: String, _ value: JSONValue) {
        var evaluation = draft?.evaluation?.object ?? ["set": .string("eval/default")]
        evaluation[key] = value; draft?.evaluation = .object(evaluation)
    }
    private func addBlock(_ definition: BlockDefinition) {
        guard var pipeline = draft else { return }
        let index = (blockIndex ?? pipeline.blocks.count-1)+1
        let classes = model.selectedID.map { model.datasetWorkspace(for: $0).classes.map(\.name) } ?? []
        let block = PipelineBlock(id: BlockGraphEditing.uniqueID(type: definition.type, blocks: pipeline.blocks), type: definition.type, params: definition.initialParams(classes: classes), connections: [:])
        pipeline.blocks.insert(block, at: index)
        for input in definition.inputs.keys {
            let source = BlockGraphEditing.compatibleSources(pipeline: pipeline, blockIndex: index, input: input, catalog: catalog).last?.reference ?? ""
            pipeline.blocks[index].connections?[input] = .string(source)
        }
        if definition.type == "vlm_judge" {
            pipeline.blocks[index].params?["base_url"] = .string(model.settings.vlmUrl)
            pipeline.blocks[index].params?["model"] = .string(model.settings.vlmModel)
        }
        draft = pipeline; selectedBlock = block.id; resetJSON()
    }
    private func removeBlock(_ index: Int) {
        guard var pipeline = draft, pipeline.blocks.indices.contains(index), pipeline.blocks.count > 1 else { return }
        pipeline.blocks.remove(at: index); draft = pipeline; selectedBlock = pipeline.blocks[min(index,pipeline.blocks.count-1)].id; resetJSON()
    }
    private func moveBlock(_ index: Int, offset: Int) {
        guard var pipeline = draft, pipeline.blocks.indices.contains(index+offset) else { return }
        pipeline.blocks.swapAt(index, index+offset); draft = pipeline
    }
    private func connectionPicker(_ key: String, index: Int) -> some View {
        let choices = draft.map { BlockGraphEditing.compatibleSources(pipeline: $0, blockIndex: index, input: key, catalog: catalog) } ?? []
        let current = draft?.blocks[index].connections?[key]?.string ?? ""
        let missing = !current.isEmpty && !choices.contains(where: { $0.reference == current })
        return VStack(alignment: .leading, spacing: 5) {
            Picker(key, selection: Binding(get: { draft?.blocks[index].connections?[key]?.string ?? "" }, set: { draft?.blocks[index].connections?[key] = .string($0) })) {
                Text("Choose upstream output").tag("")
                if missing { Text("Unresolved: " + current).tag(current) }
                ForEach(choices) { choice in Text("\(choice.reference) · \(choice.type)").tag(choice.reference) }
            }
            if missing || current.isEmpty { Text("Connect this input before saving.").font(.caption).foregroundStyle(.orange) }
        }
    }
    private func resetJSON() {
        guard let index = blockIndex else { jsonDraft = "{}"; return }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        jsonDraft = (try? encoder.encode(draft?.blocks[index].params ?? [:])).flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        jsonError = nil
    }
    private func applyJSON(index: Int) {
        do { draft?.blocks[index].params = try JSONDecoder().decode([String: JSONValue].self, from: Data(jsonDraft.utf8)); jsonError = nil }
        catch { jsonError = "Parameters must be a valid JSON object: \(error.localizedDescription)" }
    }
}
