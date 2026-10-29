import SwiftUI

struct ZonesView: View {
    @EnvironmentObject var model: WorkspaceModel
    @NativeState<String> private var zoneName = "Region 1"
    private var requestedByAgent: Bool {
        guard let id = model.selectedID else { return false }
        return model.agentWorkspace(for: id).build?.nextAction == "define_zones"
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Mark the actual regions in your image").font(.title3.weight(.medium))
                        Text("Use the names referenced in your goal, then draw their boundaries.").font(.callout).foregroundStyle(Studio.muted)
                    }
                    Spacer()
                    Button("Back to Agent") { model.section = "Agent" }
                    Button(requestedByAgent ? "Save regions and continue building" : "Save regions") { model.saveZones(continueBuilding: requestedByAgent) }
                        .buttonStyle(.borderedProminent).disabled(model.zones.isEmpty || model.busy)
                }
                if !model.zones.isEmpty && !model.zonesConfirmed {
                    Label("Unconfirmed regions. Check or redraw this geometry before saving; it is not established task input yet.", systemImage: "exclamationmark.triangle")
                        .font(.callout).foregroundStyle(.orange)
                } else if model.zonesConfirmed {
                    Text(model.zonesOrigin == "fixture" ? "Fixture geometry · synthetic walkthrough" : "Saved user-defined geometry").font(.caption).foregroundStyle(Studio.muted)
                }
                HStack(alignment: .top, spacing: 20) {
                    VStack(alignment: .leading, spacing: 14) {
                        ImageCanvas(path: model.project?.media.first, zones: model.zones, onDraw: { box in
                            let name = zoneName.trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !name.isEmpty else { model.error = "Name the region before drawing its boundary."; return }
                            model.zones.removeAll { $0.id == name }
                            model.zones.append(Zone(id: name, polygon: [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]))
                            model.zonesConfirmed = false; model.zonesOrigin = "unconfirmed"
                            zoneName = "Region \(model.zones.count + 1)"
                        }, emptyTitle: "Reference image needed", emptyDetail: "Add an example image so you can mark its actual regions.")
                            .frame(minHeight: 470)
                        Text("Drag to draw a rectangular region. Reusing a name replaces that region's boundary. Coordinates belong to this image and are normalized.").font(.caption).foregroundStyle(Studio.muted)
                    }.panel()
                    VStack(alignment: .leading, spacing: 16) {
                        Text("Region name").font(.headline)
                        TextField("For example: Loading area", text: $zoneName).textFieldStyle(.roundedBorder)
                        ForEach(model.zones) { zone in
                            HStack { Label(zone.id, systemImage: "square.dashed"); Spacer(); Button { model.zones.removeAll { $0.id == zone.id }; model.zonesConfirmed = false } label: { Image(systemName: "trash") }.buttonStyle(.plain) }
                        }
                        Text("Saving confirms your geometry and invalidates earlier evaluation evidence. The agent then continues the original goal using these regions.").font(.caption).foregroundStyle(Studio.muted)
                    }.frame(width: 235).panel()
                }
            }.padding(.horizontal, 28).padding(.bottom, 24)
        }
    }
}
