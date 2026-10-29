import Foundation

enum AlertKind: String, Codable, CaseIterable, Identifiable {
    case webhook, smtp, mqtt
    var id: String { rawValue }
    var title: String {
        switch self { case .webhook: return "Webhook"; case .smtp: return "Email · SMTP"; case .mqtt: return "MQTT" }
    }
    var symbol: String {
        switch self { case .webhook: return "link"; case .smtp: return "envelope"; case .mqtt: return "antenna.radiowaves.left.and.right" }
    }
}
enum AlertTLS: String, Codable, CaseIterable {
    case tls, starttls, none
    var title: String {
        switch self { case .tls: return "TLS"; case .starttls: return "STARTTLS"; case .none: return "No TLS" }
    }
}
struct AlertTarget: Codable, Identifiable, Equatable {
    var id: String
    var name: String
    var kind: AlertKind
    var enabled: Bool
    var url: String?
    var host: String?
    var port: Int?
    var username: String?
    var hasSecret: Bool
    var fromAddress: String?
    var recipients: [String]?
    var topic: String?
    var tlsMode: AlertTLS?
    enum CodingKeys: String, CodingKey {
        case id, name, kind, enabled, url, host, port, username, recipients, topic
        case hasSecret = "has_secret", fromAddress = "from_address", tlsMode = "tls_mode"
    }
    static func blank(kind: AlertKind) -> AlertTarget {
        var target = AlertTarget(id: UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: ""), name: "", kind: kind, enabled: true, hasSecret: false)
        target.setTransport(kind)
        return target
    }
    mutating func setTransport(_ kind: AlertKind) {
        self.kind = kind; url = nil; host = nil; port = nil; username = nil
        fromAddress = nil; recipients = nil; topic = nil; tlsMode = nil
        switch kind {
        case .webhook: url = ""
        case .smtp: host = ""; port = 587; username = ""; fromAddress = ""; recipients = []; tlsMode = .starttls
        case .mqtt: host = ""; port = 8883; username = ""; topic = "visionapp/events"; tlsMode = .tls
        }
    }
    var destination: String {
        switch kind {
        case .webhook: return url?.isEmpty == false ? url! : "No URL set"
        case .smtp: return "\((recipients ?? []).joined(separator: ", ")) via \(host ?? ""):\(port ?? 587)"
        case .mqtt: return "\(host ?? ""):\(port ?? 8883) / \(topic ?? "")"
        }
    }
    var validationMessage: String? {
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Give this target a name." }
        switch kind {
        case .webhook:
            guard let raw = url, let parsed = URLComponents(string: raw), ["http", "https"].contains(parsed.scheme?.lowercased() ?? ""), parsed.host?.isEmpty == false else { return "Enter a complete http or https webhook URL." }
            if parsed.user != nil || parsed.password != nil { return "Keep credentials out of the webhook URL. Use the secure token field." }
        case .smtp, .mqtt:
            if host?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false { return "Enter a server hostname." }
            if !(1...65535).contains(port ?? 0) { return "Enter a port between 1 and 65535." }
            if kind == .smtp {
                if fromAddress?.contains("@") != true { return "Enter the sender email address." }
                if recipients?.isEmpty != false || recipients?.contains(where: { !$0.contains("@") || $0.contains("\n") || $0.contains("\r") }) == true { return "Enter at least one recipient email address." }
            }
            if kind == .mqtt && topic?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false { return "Enter the MQTT topic." }
        }
        return nil
    }
}
struct AlertConfiguration: Codable, Equatable {
    var revision: Int
    var enabled: Bool
    var minimumIntervalS: Double
    var targets: [AlertTarget]
    enum CodingKeys: String, CodingKey { case revision, enabled, targets, minimumIntervalS = "minimum_interval_s" }
    static let empty = AlertConfiguration(revision: 0, enabled: false, minimumIntervalS: 60, targets: [])
}
struct AlertSaveRequest: Encodable {
    var approved = true
    var configuration: AlertConfiguration
    var secrets: [String: JSONValue]
}
enum AlertDeliveryStatus: String, Codable {
    case queued, sending, sent, failed, cancelled
    var canRetry: Bool { self == .failed }
}
struct AlertDelivery: Codable, Identifiable {
    var id: String
    var targetID: String
    var targetName: String
    var eventID: String
    var createdAt: String
    var status: AlertDeliveryStatus
    var attempts: Int
    var error: String?
    var sentAt: String?
    enum CodingKeys: String, CodingKey {
        case id, status, attempts, error
        case targetID = "target_id", targetName = "target_name", eventID = "event_id"
        case createdAt = "created_at", sentAt = "sent_at"
    }
}
enum AlertApproval: Identifiable {
    case save, test(AlertTarget), retry(AlertDelivery, AlertTarget), refresh
    var id: String {
        switch self { case .save: return "save"; case .test(let target): return "test-" + target.id
        case .retry(let delivery, _): return "retry-" + delivery.id; case .refresh: return "refresh" }
    }
}
