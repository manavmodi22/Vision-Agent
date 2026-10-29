import Foundation

struct CapabilityEvidence: Codable {
    let kind: String
    let subject: String
    let outcome: String
    let detail: String
    let observedAt: String
    let metadata: [String: JSONValue]
    enum CodingKeys: String, CodingKey { case kind, subject, outcome, detail, metadata, observedAt = "observed_at" }
}
struct CapabilityReadiness: Codable {
    let state: String
    let reason: String
    let checkedAt: String
    let evidenceScope: String
    let evidence: [CapabilityEvidence]
    enum CodingKeys: String, CodingKey { case state, reason, evidence, checkedAt = "checked_at", evidenceScope = "evidence_scope" }
}
struct CapabilityLicense: Codable {
    let identifier: String
    let code: String?
    let weights: String?
    let status: String
    let notes: [String]
}
struct CapabilityProvenance: Codable {
    let sourceURLs: [String]
    let revision: String?
    let hashes: [String: String]
    let scope: String
    let notes: [String]
    enum CodingKeys: String, CodingKey { case revision, hashes, scope, notes, sourceURLs = "source_urls" }
}
struct CapabilityHardware: Codable {
    let platforms: [String]
    let accelerators: [String]
    let requiredPackages: [String]
    let minimumMemoryGiB: Double?
    let estimatedDiskBytes: Int64?
    let notes: [String]
    enum CodingKeys: String, CodingKey {
        case platforms, accelerators, notes, requiredPackages = "required_packages"
        case minimumMemoryGiB = "minimum_memory_gib", estimatedDiskBytes = "estimated_disk_bytes"
    }
}
struct Capability: Codable, Identifiable {
    let id: String
    let name: String
    let kind: String
    let description: String
    let availability: String
    let implemented: Bool
    let installationReady: Bool
    let callable: Bool
    let taskTypes: [String]
    let version: String?
    let license: CapabilityLicense
    let provenance: CapabilityProvenance
    let hardware: CapabilityHardware
    let sideEffects: [String]
    let dependencies: [String]
    let inputSchema: [String: JSONValue]
    let outputSchema: [String: JSONValue]
    let installMethod: String
    let installInstructions: String?
    let readiness: CapabilityReadiness
    enum CodingKeys: String, CodingKey {
        case id, name, kind, description, availability, implemented, callable, version, license, provenance, hardware, dependencies, readiness
        case installationReady = "installation_ready", taskTypes = "task_types", sideEffects = "side_effects"
        case inputSchema = "input_schema", outputSchema = "output_schema", installMethod = "install_method", installInstructions = "install_instructions"
    }
    var verifiedCallable: Bool { availability == "installed" && implemented && installationReady && callable && readiness.state == "ready" }
    var eligibleForValidation: Bool { availability == "installed" && implemented && installationReady }
    var validationEligibilityMessage: String? {
        guard !verifiedCallable else { return nil }
        return eligibleForValidation ? "Eligible for a bounded validation; not yet verified." : "Not eligible for bounded validation in its current state."
    }
    func matches(_ search: String) -> Bool {
        search.isEmpty || ([name, id, description] + taskTypes).joined(separator: " ").localizedCaseInsensitiveContains(search)
    }
}
struct CapabilityCatalog: Codable {
    let schemaVersion: String
    let generatedAt: String
    let host: [String: JSONValue]
    let capabilities: [Capability]
    enum CodingKeys: String, CodingKey { case schemaVersion = "schema_version", generatedAt = "generated_at", host, capabilities }
}

@MainActor final class CapabilityStore: ObservableObject {
    let client: EngineClient
    @Published var catalog: CapabilityCatalog?
    @Published var loading = false
    @Published var error: String?
    @Published var provisioningOptions: [ProvisioningOption] = []
    @Published var provisioningError: String?
    init(client: EngineClient) { self.client = client }
    func refresh() async {
        guard !loading else { return }; loading = true
        defer { loading = false }
        do { catalog = try await client.request("GET", "/capabilities"); error = nil }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
        do { let result: ProvisioningOptions = try await client.request("GET", "/provisioning/options"); provisioningOptions = result.options; provisioningError = nil }
        catch { provisioningOptions = []; provisioningError = error.localizedDescription }
    }
}
