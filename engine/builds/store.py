"""Persist progress and enforce evidence-bound budgets for build MCP actions."""

import hashlib
import json
import os
import re
import uuid
from time import time, time_ns

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent.machine import AgentBudget, AgentConflict, AgentState, Phase
from agent.refinement_capabilities import delivery_question
from agent.refinement_contracts import RefinementDecision
from agent.state_contracts import AgentOperation, CapturedCall
from engine.agent_traces import AgentTraceStore
from engine.eval import dataset_hash, spec_hash
from engine.media import media_fingerprint
from engine.platform.store import PlatformStore
from engine.service import WorkspaceService
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.build import BuildLog, BuildStatus
from spec.skills import SkillReference


class BuildRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view: BuildStatus
    operation: AgentOperation
    prompt: str
    data_hash: str
    plan_operation_id: str | None = None
    training_approved_hash: str | None = None
    training_attempts: int = 0
    training_job_id: str | None = None
    refinement_decisions: list[dict[str, JsonValue]] = Field(default_factory=list)
    skills: list[SkillReference] = Field(default_factory=list)


class BuildStore:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.traces = AgentTraceStore(service.repository.root)
        self.platform = PlatformStore(service)

    def inputs_hash(self, project_id: str) -> str:
        project, root = self.service.get_project(project_id), self.service.root(project_id)
        metadata_path = root / "dataset-metadata.json"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        value = {"media": media_fingerprint(project.media),
                 "candidates": [spec_hash(spec, root) for spec in project.candidates],
                 "classes": sorted(item["name"] for item in metadata.get("classes", [])),
                 "holdout": (root / "active-holdout.json").read_text() if (root / "active-holdout.json").exists() else None,
                 "zones": {path.name: path.read_text() for path in sorted((root / "zones").glob("*.json"))}}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def labels_hash(self, project_id: str) -> str:
        return dataset_hash(self.service.annotations(project_id), self.service.root(project_id))

    def save(self, record: BuildRecord) -> None:
        record.view.updated_at = now()
        record.operation.updated_at = time()
        record.view.project = {}  # Hydrated at response time, never replay an old project snapshot.
        record.view.plan, record.view.execution, record.view.tool_events = None, None, []
        root = self.service.root(record.view.project_id)
        atomic_model(root / "builds" / f"{record.view.id}.json", record)
        atomic_model(root / "build.json", record)

    def get(self, project_id: str, build_id: str | None = None) -> BuildRecord:
        with self.service.repository.lock:
            if build_id is not None and not re.fullmatch(r"[0-9a-f]{32}", build_id):
                raise ValueError("Invalid build identifier")
            path = self.service.root(project_id) / "build.json"
            if not path.exists():
                raise FileNotFoundError("No build has been started for this project")
            record = BuildRecord.model_validate_json(path.read_text())
            if build_id and record.view.id != build_id:
                raise AgentConflict("This build was superseded by a new goal")
            alive = True
            try:
                os.kill(record.operation.owner_pid, 0)
            except ProcessLookupError:
                alive = False
            if record.view.status == "running" and (not alive or time() > record.operation.deadline):
                self.pause(record, "interrupted", "retry", "The build worker stopped. Continue to resume from the last safe step.")
                for call in record.operation.calls:
                    if call.status == "running":
                        call.status, call.error, call.ended_ns = "interrupted", record.view.message, time_ns()
                        self.platform.record_call(project_id, record.view.id, call, record.operation.state.phase)
                        self.traces.emit(record.operation, call)
                self.save(record)
            return record

    def public(self, record: BuildRecord) -> BuildStatus:
        project_id = record.view.project_id
        plans = self.platform.plans(project_id, record.view.id)
        plan = plans[-1] if plans else None
        execution = self.platform.execution(project_id, plan.operation_id) if plan else None
        return record.view.model_copy(update={"project": self.service.get_project(project_id).model_dump(mode="json", by_alias=True),
            "plan": plan, "execution": execution, "tool_events": self.platform.events(project_id, record.view.id)}, deep=True)

    def create(self, project_id: str, prompt: str) -> BuildRecord:
        with self.service.repository.lock:
            try:
                prior = self.get(project_id)
            except FileNotFoundError:
                prior = None
            if prior and prior.view.status == "running":
                raise AgentConflict("A build is already running for this project")
            identifier, stamp = uuid.uuid4().hex, now()
            record = BuildRecord(view=BuildStatus(id=identifier, project_id=project_id, status="running", phase="planning",
                message="Interpreting your goal and preparing a working preview", created_at=stamp, updated_at=stamp,
                selected_candidate_index=prior.view.selected_candidate_index if prior else None), prompt=prompt,
                data_hash=self.labels_hash(project_id), operation=AgentOperation(id=identifier, project_id=project_id,
                trace_id=uuid.uuid4().hex, root_span_id=uuid.uuid4().hex[:16], owner_pid=os.getpid(), deadline=time() + 900,
                input_fingerprint=self.inputs_hash(project_id), brief=prompt, source_path="media", detector_model="",
                state=AgentState(phase=Phase.PLAN, budget=AgentBudget(max_tool_calls=30, max_wall_seconds=900, max_training_minutes=4))))
            self.log(record, "planning", record.view.message)
            self.save(record)
            return record

    def log(self, record: BuildRecord, phase: str, message: str) -> None:
        record.view.phase, record.view.message = phase, message
        record.view.log.append(BuildLog(at=now(), phase=phase, message=message))
        record.view.log = record.view.log[-100:]

    def pause(self, record: BuildRecord, status: str, next_action: str, message: str) -> None:
        # Revalidate enum values at this small dynamic orchestration boundary.
        record.view = BuildStatus.model_validate({**record.view.model_dump(), "status": status, "next_action": next_action})
        self.log(record, record.view.phase, message)
        self.save(record)
        self.platform.close(record.view.project_id, record.view.id,
                            status if status in {"completed", "failed", "interrupted"} else "paused",
                            message if status in {"failed", "interrupted"} else None)

    def refresh_inputs(self, record: BuildRecord) -> None:
        record.operation.input_fingerprint = self.inputs_hash(record.view.project_id)
        record.data_hash = self.labels_hash(record.view.project_id)

    def assert_current(self, record: BuildRecord, *, allow_labels: bool = False) -> None:
        project_id = record.view.project_id
        if self.inputs_hash(project_id) != record.operation.input_fingerprint:
            raise AgentConflict("Media, classes, zones or workflow changed. Describe the updated goal to rebuild safely.")
        if not allow_labels and self.labels_hash(project_id) != record.data_hash:
            raise AgentConflict("Annotations changed during active work. Continue after reviewing the current labels.")

    def start_call(self, project_id: str, build_id: str, name: str, request: dict[str, JsonValue]) -> CapturedCall:
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            if record.view.status != "running":
                raise AgentConflict("Build tools are only available while the build is active")
            if any(call.status == "running" for call in record.operation.calls):
                raise AgentConflict("Another action is already in progress for this build")
            self.assert_current(record)
            record.operation.state.authorize_tool(name)
            if request.get("project_id") != project_id:
                raise AgentConflict("Build tools cannot access another project")
            if name == "build_operate" and any(call.name == name and call.request == request for call in record.operation.calls):
                raise AgentConflict("This recorded run was already attempted; inspect its evidence instead of repeating effects")
            if name == "build_refine":
                from engine.platform.proposals import refinement_candidates
                if record.skills:
                    self.record_skills(project_id, build_id, record.skills)
                self.platform.publish(project_id, build_id, record.prompt,
                    refinement_candidates(self.service, project_id, request), record.operation.state.phase,
                    "Requested typed graph edits before compilation and preview", build_id=build_id, skills=record.skills)
            elif record.operation.state.phase != Phase.PLAN:
                execution = self.platform.execution(project_id, build_id)
                if execution is None or execution.phase != record.operation.state.phase.value or execution.status != "running":
                    self.platform.publish(project_id, build_id, record.prompt,
                        self.service.get_project(project_id).candidates, record.operation.state.phase,
                        "Next authorized experiment on the current project snapshot", build_id=build_id)
            if name == "build_refine" or record.operation.state.phase != Phase.PLAN:
                self.platform.authorize(project_id, build_id, record.operation.state.phase, name, request)
            call = CapturedCall(id=uuid.uuid4().hex, kind="tool", name=name, request=request, started_ns=time_ns())
            record.operation.calls.append(call)
            self.platform.record_call(project_id, build_id, call, record.operation.state.phase)
            self.save(record)
            return call

    def finish_call(self, project_id: str, build_id: str, call_id: str, output: dict[str, JsonValue] | None,
                    error: str | None = None) -> BuildRecord:
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            call = next(item for item in record.operation.calls if item.id == call_id)
            if call.status != "running":
                raise AgentConflict("Build call is already finished")
            call.result, call.error, call.ended_ns = output, error, time_ns()
            call.status = "failed" if error else "completed"
            self.platform.record_call(project_id, build_id, call, record.operation.state.phase)
            if error:
                self.platform.close(project_id, build_id, "failed", error)
            if not error and call.name in {"build_propose_labels", "build_train", "build_refine", "build_prepare_review"}:
                self.refresh_inputs(record)
                execution = self.platform.execution(project_id, build_id)
                if execution:
                    before = execution.accepted_snapshot
                    self.platform.accept_effect(project_id, build_id)
                    after = self.platform.execution(project_id, build_id)
                    if after and (before != after.accepted_snapshot or call.name == "build_refine"):
                        self.platform.close(project_id, build_id, "completed")
            self.save(record)
            self.traces.emit(record.operation, call)
            return record

    def start_model_call(self, project_id: str, build_id: str, name: str,
                         request: dict[str, JsonValue]) -> CapturedCall:
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            if (record.view.status != "running" or record.view.phase != "planning"
                    or record.operation.state.phase != Phase.PLAN):
                raise AgentConflict("Refinement interpretation is only available during active planning")
            if any(call.status == "running" for call in record.operation.calls):
                raise AgentConflict("Another action is already in progress for this build")
            self.assert_current(record)
            record.operation.state.budget.consume_model()
            call = CapturedCall(id=uuid.uuid4().hex, kind="llm", name=name, request=request, started_ns=time_ns())
            record.operation.calls.append(call)
            self.platform.record_call(project_id, build_id, call, record.operation.state.phase)
            self.save(record)
            return call

    def record_refinement_decision(self, project_id: str, build_id: str,
                                   decision: dict[str, JsonValue]) -> AgentState:
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            if record.view.status != "running" or record.view.phase != "planning":
                raise AgentConflict("The refinement operation is no longer active")
            self.assert_current(record)
            parsed = RefinementDecision.model_validate(decision)
            project = self.service.get_project(project_id)
            question = delivery_question(record.prompt, project.messages[-1].content if project.messages else "")
            if parsed.source == "capability_guard":
                if question is None or parsed.questions != [question] or parsed.message != question:
                    raise AgentConflict("The capability question must match this build's actual user request")
                if project.clarification_count >= 3:
                    raise AgentConflict("The three-question budget is exhausted")
                record.refinement_decisions.append(parsed.model_dump(mode="json"))
                self.save(record)
                return record.operation.state
            if question and parsed.patches:
                raise AgentConflict(question)
            calls = [call for call in record.operation.calls if call.kind == "llm" and call.status == "completed"]
            if not calls:
                raise AgentConflict("A conversational refinement needs a captured local-model response")
            raw = calls[-1].result or {}
            captured: object = raw.get("decision")  # Explicit deterministic test models use this envelope.
            messages = raw.get("messages")
            if isinstance(messages, list):
                text_parts: list[str] = []
                for message in messages:
                    parts = message.get("parts") if isinstance(message, dict) else None
                    if isinstance(parts, list):
                        for part in parts:
                            content = part.get("content") if isinstance(part, dict) else None
                            if isinstance(part, dict) and part.get("part_kind") == "text" and isinstance(content, str):
                                text_parts.append(content)
                try:
                    captured = json.loads("".join(text_parts))
                except (TypeError, ValueError) as error:
                    raise AgentConflict("The captured model response has no typed refinement decision") from error
            if RefinementDecision.model_validate(captured).model_dump(mode="json") != decision:
                raise AgentConflict("The decision differs from the captured model response")
            record.refinement_decisions.append(decision)
            self.save(record)
            return record.operation.state

    def record_skills(self, project_id: str, build_id: str, skills: list[SkillReference]) -> AgentState:
        from agent.skills import select_skills
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            self.assert_current(record)
            expected = [item.reference for item in select_skills(record.prompt, self.service.get_project(project_id).use_case)]
            if record.view.status != "running" or record.operation.state.phase != Phase.PLAN or skills != expected:
                raise AgentConflict("Refinement skill references changed; reinterpret against the installed playbooks")
            record.skills = skills
            record.operation.skills = skills
            self.save(record)
            return record.operation.state

    def consume_training_approval(self, project_id: str, build_id: str, candidate_index: int) -> None:
        with self.service.repository.lock:
            record = self.get(project_id, build_id)
            self.assert_current(record)
            fingerprint = record.operation.input_fingerprint + record.data_hash
            if (record.view.status != "running" or record.view.phase != "training"
                    or record.training_approved_hash != fingerprint
                    or candidate_index != record.view.selected_candidate_index):
                raise AgentConflict("Training needs a current, explicit human approval for this build and candidate")
            record.training_approved_hash = None
            self.save(record)
