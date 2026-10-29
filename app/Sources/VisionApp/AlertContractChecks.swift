import Foundation

/// Wire-contract checks run by the native CLI and the XCTest target.
enum AlertContractChecks {
    static func run() throws -> Int {
        var checks = 0
        func require(_ value: Bool, _ message: String) throws {
            guard value else { throw EngineError.protocolError("Alert contract check failed: " + message) }
            checks += 1
        }
        let data = Data("""
        {"revision":7,"enabled":false,"minimum_interval_s":60,"targets":[{"id":"ops","name":"Operations","kind":"webhook","enabled":true,"url":"https://example.com/events","has_secret":true}]}
        """.utf8)
        let configuration = try JSONDecoder().decode(AlertConfiguration.self, from: data)
        try require(configuration.revision == 7 && configuration.targets[0].hasSecret, "public configuration decode")
        let preserve = AlertSaveRequest(configuration: configuration, secrets: [:])
        let preserved = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(preserve))
        try require(preserved.object["secrets"]?.object.isEmpty == true, "omitted secret preserves stored credential")
        let remove = AlertSaveRequest(configuration: configuration, secrets: ["ops": .null])
        let removed = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(remove))
        try require(removed.object["secrets"]?.object["ops"] == .null, "explicit null removes credential")
        let replace = AlertSaveRequest(configuration: configuration, secrets: ["ops": .string("generated-test-token")])
        let replaced = try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(replace))
        try require(replaced.object["secrets"]?.object["ops"] == .string("generated-test-token"), "replacement secret is write-only request data")
        let publicData = try JSONEncoder().encode(configuration)
        try require(String(data: publicData, encoding: .utf8)?.contains("generated-test-token") == false, "public configuration cannot contain submitted secret")
        try require(preserved.object["approved"] == .bool(true), "explicit approval payload")
        let receipt = try JSONDecoder().decode(AlertDelivery.self, from: Data("""
        {"id":"delivery-1","target_id":"ops","target_name":"Operations","event_id":"generated-test","created_at":"2026-10-28T00:00:00Z","status":"failed","attempts":1,"error":"Connection refused","sent_at":null}
        """.utf8))
        try require(receipt.status.canRetry && !AlertDeliveryStatus.cancelled.canRetry, "retry failed only; cancelled stays cancelled")
        try require(receipt.targetID == "ops" && receipt.error == "Connection refused", "receipt fields")
        var smtp = AlertTarget.blank(kind: .smtp)
        smtp.name = "Email"; smtp.host = "localhost"; smtp.fromAddress = "vision@example.com"; smtp.recipients = ["ops@example.com"]
        try require(smtp.validationMessage == nil && smtp.destination.contains("ops@example.com"), "email destination summary")
        smtp.setTransport(.mqtt)
        try require(smtp.fromAddress == nil && smtp.recipients == nil && smtp.port == 8883 && smtp.tlsMode == .tls, "transport changes remove irrelevant destinations")
        var webhook = configuration.targets[0]
        webhook.url = "https://user:password@example.com/events"
        try require(webhook.validationMessage != nil, "credentials cannot hide in URL authority")
        return checks
    }
}
