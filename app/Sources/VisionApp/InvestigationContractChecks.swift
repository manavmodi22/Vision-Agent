import Foundation
import CryptoKit

enum InvestigationContractChecks {
    @MainActor static func run() throws -> Int {
        var checks = 0
        func require(_ condition: Bool, _ message: String) throws {
            guard condition else { throw EngineError.protocolError("Investigation check failed: " + message) }; checks += 1
        }
        func rejected(_ body: () throws -> Void) -> Bool { do { try body(); return false } catch { return true } }
        let taskID = String(repeating: "a", count: 32), actionID = String(repeating: "b", count: 32)
        let observationID = String(repeating: "c", count: 32), revisionID = String(repeating: "d", count: 32)
        let specHash = String(repeating: "e", count: 64)
        var state: [String: JSONValue] = ["schema_version": .string("a0.1"), "id": .string(taskID), "project_id": .string("native-test"), "objective": .string("Read é and 東京"), "revision": .number(4), "status": .string("running"), "stage": .string("workflow"), "selected_workflow_revision": .null, "preview_observation_id": .null, "pending_action_id": .string(actionID), "pending_model_call_id": .null, "latest_observation_ids": .array([]), "question": .null, "stop_reason": .null, "user_answers": .array([]), "created_at": .string("2026-10-29T00:00:00Z"), "updated_at": .string("2026-10-29T00:01:00Z"), "budget": .object(["max_model_calls": .number(20), "max_actions": .number(16), "max_probes": .number(6), "max_elapsed_s": .number(900), "model_calls": .number(3), "actions": .number(2), "probes": .number(1), "elapsed_s": .number(15)])]
        func decodeState(_ value: [String: JSONValue]) throws -> InvestigationState { try JSONDecoder().decode(InvestigationState.self, from: JSONEncoder().encode(value)) }
        let working = try decodeState(state)
        try require(working.running && !working.resumable && !working.terminal && working.statusLabel == "Constructing a workflow", "workflow stage is work in progress")
        try require(working.budget.probes == 1 && working.budget.maxProbes == 6, "persisted budget counters survive reconnect")
        try require(InvestigationPresentation.controlBody(working, action: "pause") == ["expected_revision": .number(4), "action": .string("pause")], "pause has exact revision and no approval flags")
        try require(InvestigationPresentation.resumeBody(working, answer: "é 東京") == ["expected_revision": .number(4), "answer": .string("é 東京")], "answer keeps Unicode and revision")
        try require(InvestigationPresentation.resumeBody(working, answer: "  ").count == 1, "resume without answer does not send an empty answer")
        state["status"] = .string("paused"); let paused = try decodeState(state)
        try require(paused.resumable && paused.cancellable && !paused.running, "paused sessions stay paused until explicit resume")
        state["status"] = .string("future_status"); let unknown = try decodeState(state)
        try require(!unknown.resumable && !unknown.cancellable && !unknown.terminal, "unknown status grants no controls or replacement")
        state["status"] = .string("paused"); state["schema_version"] = .string("a9"); let future = try decodeState(state)
        try require(!future.resumable && !future.cancellable, "future runtime never gains mutation controls")
        state["schema_version"] = .string("a0.1"); state["status"] = .string("running")
        try require(!InvestigationPresentation.accepts(working, current: nil, projectID: "other", taskID: taskID), "other project response rejected")
        try require(!InvestigationPresentation.accepts(working, current: nil, projectID: "native-test", taskID: "other"), "old task response rejected")
        state["revision"] = .number(5); let newer = try decodeState(state)
        try require(!InvestigationPresentation.accepts(working, current: newer, projectID: "native-test", taskID: taskID), "late poll cannot roll back revision")
        try require(InvestigationPresentation.accepts(newer, current: working, projectID: "native-test", taskID: taskID), "newer same-task response accepted")
        let reading: [String: JSONValue] = ["text": .string("東京 é\u{0301}"), "kind": .string("ocr"), "box": .array([.number(0.1), .number(0.2), .number(0.8), .number(0.7)]), "polygon": .null, "confidence": .number(0.8), "symbology": .null, "item_id": .string("actual-item")]
        let rows = InvestigationProbePresentation.readings([reading])
        try require(rows.count == 1 && rows[0].observation.text == "東京 é\u{0301}" && rows[0].observation.box == [0.1, 0.2, 0.8, 0.7], "probe keeps Unicode and actual input geometry")
        try require(rows[0].blockID.isEmpty && rows[0].id == "actual-item", "graphless observation does not invent a workflow block")
        var invalidReading = reading; invalidReading["box"] = .array([.number(-1), .number(0), .number(1), .number(1)])
        try require(InvestigationProbePresentation.readings([invalidReading])[0].observation.box == nil, "invalid geometry does not fabricate a region")
        let comparison: JSONValue = .object(["block_id": .string("match"), "expected": .string("東京"), "observed": .array([.string("東京")]), "mode": .string("exact"), "matched": .bool(true)])
        let frame: JSONValue = .object(["image_path": .string("/not-read-by-decode.png"), "detections": .array([]), "counts": .object([:]), "texts": .array([.string("東京")]), "events": .array([]), "elapsed_ms": .number(8), "comparisons": .array([comparison])])
        var payload: [String: JSONValue] = ["workflow_revision_id": .string(revisionID), "validated": .bool(true), "preview_success": .bool(true), "spec_hash": .string(specHash), "preview_spec_hash": .string(specHash), "preview_media_ids": .array([.string("media1")]), "preview": .object(["frames": .array([frame]), "elapsed_s": .number(0.1), "warnings": .array([])])]
        var action: [String: JSONValue] = ["id": .string(actionID), "model_call_id": .string(String(repeating: "f", count: 32)), "decision": .object(["type": .string("workflow_decision"), "state_revision": .number(3), "decision_summary": .string("Test the reader on the inspected example"), "based_on_observation_ids": .array([]), "action": .object(["type": .string("construct_workflow"), "media_ids": .array([.string("media1")])])]), "status": .string("completed"), "observation_id": .string(observationID), "started_at": .string("start"), "ended_at": .string("end")]
        state["selected_workflow_revision"] = .string(revisionID); state["preview_observation_id"] = .string(observationID)
        func snapshot() throws -> InvestigationSnapshot {
            let observation: JSONValue = .object(["id": .string(observationID), "action_id": .string(actionID), "result_type": .string("construct_workflow"), "status": .string("completed"), "payload": .object(payload), "error": .null, "created_at": .string("now")])
            return try JSONDecoder().decode(InvestigationSnapshot.self, from: JSONEncoder().encode(JSONValue.object(["state": .object(state), "actions": .array([.object(action)]), "observations": .array([observation])])))
        }
        let valid = try snapshot()
        try require(valid.selectedDraft?.preview.frames[0].comparisons?.first?.matched == true && valid.state.running, "actual preview comparison can exist while agent still investigates")
        try require(valid.selectedDraft?.preview.frames[0].events.isEmpty == true, "comparison independent of saved events")
        state["status"] = .string("draft_ready")
        try require(try snapshot().selectedDraft != nil, "draft ready references actual selected preview")
        payload["preview_spec_hash"] = .string("wrong"); try require(try snapshot().selectedDraft == nil, "mismatched spec preview rejected")
        payload["preview_spec_hash"] = .string(specHash); payload["preview_media_ids"] = .array([.string("another")])
        try require(try snapshot().selectedDraft == nil, "swapped preview media rejected")
        payload["preview_media_ids"] = .array([.string("media1")]); action["status"] = .string("failed")
        try require(try snapshot().selectedDraft == nil, "failed construct does not select successful-looking payload")
        action["status"] = .string("completed"); payload["preview_success"] = .bool(false)
        try require(try snapshot().selectedDraft == nil, "compiler validation without actual preview is not a draft")
        payload["preview_success"] = .bool(true)
        var causal = valid
        var next = action; next["id"] = .string("next"); next["observation_id"] = .null
        next["decision"] = .object(["type": .string("next_action"), "state_revision": .number(6), "decision_summary": .string("Choose the next experiment"), "based_on_observation_ids": .array([.string(observationID)]), "action": .object(["type": .string("inspect_observation")])])
        causal.actions.append(try JSONDecoder().decode(InvestigationActionRecord.self, from: JSONEncoder().encode(next)))
        try require(causal.nextAction(after: causal.observations[0])?.id == "next", "next action link requires cited actual observation")
        try require(valid.nextAction(after: valid.observations[0]) == nil, "no next action is invented")

        let root = FileManager.default.temporaryDirectory.appendingPathComponent("vision-native-evidence-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let artifacts = root.appendingPathComponent("projects/native-test/investigations/\(taskID)/artifacts")
        try FileManager.default.createDirectory(at: artifacts, withIntermediateDirectories: true)
        let data = Data("{\"value\":\"東京\"}".utf8)
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        let file = artifacts.appendingPathComponent(hash + ".json"); try data.write(to: file)
        let reference: [String: JSONValue] = ["artifact_id": .string(hash + ".json"), "sha256": .string(hash), "bytes": .number(Double(data.count)), "mime_type": .string("application/json")]
        let reader = InvestigationArtifacts(dataRoot: root, projectID: "native-test", taskID: taskID)
        try require(try reader.artifact(reference, mime: "application/json") == data, "owned artifact returns verified bytes")
        var bad = reference; bad["artifact_id"] = .string("../" + hash + ".json")
        try require(rejected { _ = try reader.artifact(bad, mime: "application/json") }, "artifact traversal rejected")
        try Data("tampered".utf8).write(to: file)
        try require(rejected { _ = try reader.artifact(reference, mime: "application/json") }, "changed evidence hash rejected")
        try FileManager.default.removeItem(at: file)
        let outside = root.appendingPathComponent("outside.json"); try data.write(to: outside)
        try FileManager.default.createSymbolicLink(atPath: file.path, withDestinationPath: outside.path)
        try require(rejected { _ = try reader.artifact(reference, mime: "application/json") }, "file symlink rejected even for matching bytes")
        try FileManager.default.removeItem(at: artifacts)
        let outsideDirectory = root.appendingPathComponent("outside-dir"); try FileManager.default.createDirectory(at: outsideDirectory, withIntermediateDirectories: true)
        try data.write(to: outsideDirectory.appendingPathComponent(hash + ".json"))
        try FileManager.default.createSymbolicLink(atPath: artifacts.path, withDestinationPath: outsideDirectory.path)
        try require(rejected { _ = try reader.artifact(reference, mime: "application/json") }, "ancestor symlink rejected")
        try FileManager.default.removeItem(at: artifacts)
        try FileManager.default.createDirectory(at: artifacts, withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: file.path, contents: nil)
        let oversized = try FileHandle(forWritingTo: file); try oversized.truncate(atOffset: 64 * 1024 * 1024 + 1); try oversized.close()
        try require(rejected { _ = try reader.artifact(reference, mime: "application/json") }, "oversized evidence rejected before allocation")
        let media = root.appendingPathComponent("projects/native-test/investigations/\(taskID)/workflows/\(revisionID)/media")
        try FileManager.default.createDirectory(at: media, withIntermediateDirectories: true)
        let frozen = media.appendingPathComponent("00-media1.png"); try data.write(to: frozen)
        var frozenFrame = valid.selectedDraft!.preview.frames[0]; frozenFrame.imagePath = frozen.path; frozenFrame.sourceImageSHA256 = hash
        payload["input_refs"] = .array([.object(["preview_path": .string(frozen.path), "source_sha256": .string(hash), "preview_source_sha256": .string(hash)])])
        let selectedDraft = try snapshot().selectedDraft!
        try require(try reader.previewImage(frozenFrame, draft: selectedDraft) == data, "preview reads only matching frozen revision source and hash")
        var otherFrame = frozenFrame; otherFrame.imagePath = outside.path
        try require(rejected { _ = try reader.previewImage(otherFrame, draft: selectedDraft) }, "preview cannot read an arbitrary source path")
        otherFrame = frozenFrame; otherFrame.sourceImageSHA256 = String(repeating: "0", count: 64)
        try require(rejected { _ = try reader.previewImage(otherFrame, draft: selectedDraft) }, "preview rejects mismatched source hash")
        let key = "vision.agentRuntime.native-contract-" + UUID().uuidString
        let projectID = String(key.dropFirst("vision.agentRuntime.".count))
        defer { UserDefaults.standard.removeObject(forKey: key) }
        let store = AgentWorkspaceStore(projectID: projectID, client: EngineClient(socketPath: "/no-connection"))
        store.bindRuntime(.investigation)
        let reopened = AgentWorkspaceStore(projectID: projectID, client: EngineClient(socketPath: "/no-connection"))
        try require(reopened.usingInvestigation && reopened.build == nil, "reopening session preserves runtime without inventing legacy build")
        return checks
    }
}
