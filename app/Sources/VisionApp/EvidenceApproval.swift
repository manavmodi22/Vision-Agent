import Foundation

enum EvidenceApprovalScope: String, Codable, CaseIterable {
    case promotion, localTrial = "local_trial"
    var title: String { self == .promotion ? "Quality promotion" : "Bounded local trial" }
}

struct EvidenceApprovalRequest: Encodable {
    let candidateIndex: Int
    let approved: Bool
    let approvalScope: EvidenceApprovalScope
    let overrideReason: String?
    enum CodingKeys: String, CodingKey {
        case candidateIndex = "candidate_index", approved, approvalScope = "approval_scope", overrideReason = "override_reason"
    }
}

enum EvidenceApprovalPresentation {
    static func hasRecordingApproval(_ project: Project?) -> Bool {
        project?.deploymentId != nil && ["promotion", "local_trial"].contains(project?.approvalScope ?? "")
    }
    static func canApprove(_ result: Evaluation?, scope: EvidenceApprovalScope, reason: String) -> Bool {
        guard EvaluationEvidencePresentation.hasProtocol(result) else { return false }
        if scope == .promotion { return EvaluationEvidencePresentation.canPromote(result) }
        return reason.trimmingCharacters(in: .whitespacesAndNewlines).count >= 10
    }
    static func projectStatus(_ project: Project?) -> String {
        guard project?.deploymentId != nil else { return "Draft" }
        switch project?.approvalScope {
        case "local_trial": return "Local trial approved"
        case "promotion": return "Quality promotion approved"
        default: return "Prior approval · re-evaluate"
        }
    }
    static func trialLimits(_ project: Project?) -> [String] {
        var limits: [String] = []
        if let count = project?.trialLimits?["max_frames_per_run"] { limits.append("Up to \(count) frames per recorded run") }
        if let seconds = project?.trialLimits?["max_live_duration_s"] { limits.append("Live sessions up to \(seconds) seconds") }
        return limits
    }
}
