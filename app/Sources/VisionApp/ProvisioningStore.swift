import Foundation

@MainActor final class ProvisioningStore: ObservableObject {
    let client: EngineClient
    let option: ProvisioningOption
    @Published private(set) var plan: ProvisioningPlan?
    @Published private(set) var job: ProvisioningJob?
    @Published private(set) var previousJob: ProvisioningJob?
    @Published private(set) var busy = false
    @Published var error: String?
    @Published var notice: String?
    @Published private(set) var receipt: ProvisioningHealth?
    @Published private(set) var receiptError: String?
    @Published private(set) var loadingReceipt = false
    private var receiptRequest: UUID?
    init(client: EngineClient, option: ProvisioningOption) { self.client = client; self.option = option }
    private var jobsRoute: String { "/provisioning/jobs?model_id=" + PlatformTimeline.pathComponent(option.modelID) }
    private var pendingKey: String { "vision.provisioning.pending.\(client.socketPath).\(option.modelID)" }
    var canApprove: Bool { !busy && job == nil && ProvisioningPresentation.canApprove(plan) }
    func load() async {
        guard !busy else { return }; busy = true; error = nil
        defer { busy = false }
        do {
            let jobs: [ProvisioningJob] = try await client.request("GET", jobsRoute)
            if let pending = UserDefaults.standard.string(forKey: pendingKey), !jobs.contains(where: { $0.planID == pending }) {
                let saved: ProvisioningPlan = try await client.request("GET", "/provisioning/plans/" + PlatformTimeline.pathComponent(pending))
                try validate(saved); plan = saved; job = nil; previousJob = jobs.first
                receipt = nil; receiptError = nil; receiptRequest = nil; loadingReceipt = false
                notice = "A prior start was not confirmed. No job is recorded for this reviewed plan; any retry uses the same plan identity."
                return
            }
            if let latest = jobs.first(where: { $0.modelID == option.modelID }) {
                let saved: ProvisioningPlan = try await client.request("GET", "/provisioning/plans/" + PlatformTimeline.pathComponent(latest.planID))
                try validate(saved)
                guard ProvisioningPresentation.jobMatches(latest, plan: saved) else { throw EngineError.protocolError("The saved job does not match its reviewed plan.") }
                plan = saved; job = latest
                UserDefaults.standard.removeObject(forKey: pendingKey)
                await refreshReceipt()
            } else { try await createPlan() }
        } catch { self.error = error.localizedDescription }
    }
    func reviewCurrentPlan() async {
        guard !busy, job?.active != true else { return }; busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let jobs: [ProvisioningJob] = try await client.request("GET", jobsRoute)
            if let active = jobs.first(where: { $0.modelID == option.modelID && $0.active }) {
                let saved: ProvisioningPlan = try await client.request("GET", "/provisioning/plans/" + PlatformTimeline.pathComponent(active.planID))
                try validate(saved)
                guard ProvisioningPresentation.jobMatches(active, plan: saved) else { throw EngineError.protocolError("The active job does not match its saved plan.") }
                plan = saved; job = active; notice = "An approved job is already active. Showing its recorded progress."
                receipt = nil; receiptError = nil; receiptRequest = nil; loadingReceipt = false
            } else { try await createPlan() }
            UserDefaults.standard.removeObject(forKey: pendingKey)
        }
        catch { self.error = error.localizedDescription }
    }
    private func createPlan() async throws {
        let current: ProvisioningPlan = try await client.request("POST", "/provisioning/plans", body: ["model_id": .string(option.modelID)])
        try validate(current)
        previousJob = job; job = nil; plan = current
        receipt = nil; receiptError = nil; receiptRequest = nil; loadingReceipt = false
    }
    private func validate(_ plan: ProvisioningPlan) throws {
        guard plan.modelID == option.modelID, plan.capabilityID == option.capabilityID else {
            throw EngineError.protocolError("The plan belongs to a different model or capability. Refresh the catalog before continuing.")
        }
    }
    func startApproved() async {
        guard canApprove, let reviewed = plan else { return }
        busy = true; error = nil; notice = nil
        UserDefaults.standard.set(reviewed.id, forKey: pendingKey)
        defer { busy = false }
        do {
            let result = try await client.send("POST", "/provisioning/jobs", value: ProvisioningApproval(planID: reviewed.id, planHash: reviewed.planHash, approved: true), as: ProvisioningJob.self)
            guard ProvisioningPresentation.jobMatches(result, plan: reviewed) else { throw EngineError.protocolError("The returned job does not match the approved plan.") }
            job = result
            UserDefaults.standard.removeObject(forKey: pendingKey)
            await refreshReceipt()
        } catch {
            let failure = error.localizedDescription
            // A lost response must not cause another automatic installation request.
            do {
                let jobs: [ProvisioningJob] = try await client.request("GET", jobsRoute)
                if let recovered = jobs.first(where: { ProvisioningPresentation.jobMatches($0, plan: reviewed) }) {
                    job = recovered; notice = "The start response was not confirmed. Showing the durable job recorded for this exact plan."
                    UserDefaults.standard.removeObject(forKey: pendingKey)
                    await refreshReceipt()
                }
                self.error = failure
            } catch { self.error = failure + " Could not refresh durable jobs. Reopen or refresh before trying again." }
        }
    }
    func refreshJob() async {
        guard !busy, let current = job, let plan else { return }
        do {
            let updated: ProvisioningJob = try await client.request("GET", "/provisioning/jobs/" + PlatformTimeline.pathComponent(current.id))
            guard job?.id == current.id, self.plan?.id == plan.id, self.plan?.planHash == plan.planHash else { return }
            guard updated.id == current.id, ProvisioningPresentation.jobMatches(updated, plan: plan) else { throw EngineError.protocolError("Job identity changed during refresh.") }
            job = updated; error = nil
            await refreshReceipt()
        } catch is CancellationError { }
        catch { self.error = "Job refresh failed: \(error.localizedDescription). The last recorded state remains visible." }
    }
    private func refreshReceipt() async {
        guard let capturedJob = job, capturedJob.status == "completed", let capturedPlan = plan else { return }
        guard let id = capturedJob.result?.healthReceiptID else {
            receiptRequest = nil; loadingReceipt = false; receipt = nil; receiptError = "Receipt evidence unavailable: this completed job did not record a receipt ID."; return
        }
        if let receipt, ProvisioningPresentation.receiptMatches(receipt, job: capturedJob, plan: capturedPlan) { return }
        let requestID = UUID(); receiptRequest = requestID; receipt = nil; receiptError = nil; loadingReceipt = true
        defer { if receiptRequest == requestID { loadingReceipt = false } }
        do {
            let evidence: ProvisioningHealth = try await client.request("GET", "/provisioning/health/" + PlatformTimeline.pathComponent(id))
            guard receiptRequest == requestID, job?.id == capturedJob.id, plan?.planHash == capturedPlan.planHash else { return }
            guard ProvisioningPresentation.receiptMatches(evidence, job: capturedJob, plan: capturedPlan) else {
                throw EngineError.protocolError("Receipt model, job, plan hash or evidence scope does not match the recorded operation.")
            }
            receipt = evidence
        } catch {
            guard receiptRequest == requestID, job?.id == capturedJob.id else { return }
            receiptError = "Receipt evidence unavailable: \(error.localizedDescription) The historical job result is shown separately."
        }
    }
}
