"""Application composition boundary for durable, evidence-bound agent runs."""

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from time import time, time_ns
from typing import Literal

from pydantic import JsonValue

from agent.contracts import PlanDecision, PlanResult
from agent.decisions import plan_from_context
from agent.machine import AgentConflict as AgentConflict
from agent.machine import AgentState, EvaluationEvidence, Phase
from agent.model_selection import validate_model_choices
from agent.replay import replay_operation
from agent.state_contracts import (
    AgentOperation,
    CapturedCall,
    ProjectAgentState,
    ReplayReport,
    StateChange,
)
from engine.agent_traces import AgentTraceStore
from engine.datasets import DatasetService
from engine.eval import spec_hash
from engine.media import media_fingerprint
from engine.models.manager import list_models
from engine.platform.model_request import explicit_model_ids, request_hash
from engine.platform.planning_options import validate_current_options
from engine.platform.store import PlatformStore
from engine.service import WorkspaceService
from engine.store.models import Deployment, Message, Project
from engine.store.repository import atomic_model
from engine.zones import read_zone_state
from spec.planning import PlanningOptions
from spec.skills import SkillReference


class AgentStateStore:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.repository = service.repository
        self.traces = AgentTraceStore(self.repository.root)
        self.platform = PlatformStore(service)

    def _path(self, project_id: str, operation_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            raise ValueError("Invalid agent operation identifier")
        return self.service.root(project_id) / "agent-runs" / f"{operation_id}.json"

    def operation(self, project_id: str, operation_id: str) -> AgentOperation:
        path = self._path(project_id, operation_id)
        if not path.is_file():
            raise FileNotFoundError("Agent operation not found")
        return AgentOperation.model_validate_json(path.read_text())

    def runs(self, project_id: str) -> list[AgentOperation]:
        self.get(project_id)
        paths = (self.service.root(project_id) / "agent-runs").glob("*.json")
        return sorted((AgentOperation.model_validate_json(path.read_text()) for path in paths),
                      key=lambda item: item.created_at, reverse=True)

    def replay(self, project_id: str, operation_id: str) -> ReplayReport:
        with self.repository.lock:
            return replay_operation(self.operation(project_id, operation_id))

    def _fingerprint(self, project_id: str) -> str:
        from engine.eval.protocol import stable_configuration_hash
        from engine.eval.recipe import recipe_hash
        project = self.service.get_project(project_id)
        root = self.service.root(project_id)
        classes = DatasetService(self.service).manifest(project_id).classes
        payload = {"media": media_fingerprint(project.media), "clarification_count": project.clarification_count,
                   "evaluation_configuration": stable_configuration_hash(root, self.service.annotations(project_id)),
                   "evaluation_recipe": recipe_hash(),
                   "ontology": [item.model_dump(mode="json") for item in sorted(classes, key=lambda item: item.id)],
                   "candidates": [item.model_dump(mode="json", by_alias=True) for item in project.candidates],
                   "annotations": (root / "annotations.json").read_text(),
                   "holdout": (root / "active-holdout.json").read_text() if (root / "active-holdout.json").exists() else None,
                   "zones": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted((root / "zones").glob("*.json"))}}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _record(self, project_id: str) -> ProjectAgentState:
        path = self.service.root(project_id) / "agent-state.json"
        return ProjectAgentState.model_validate_json(path.read_text()) if path.exists() else ProjectAgentState(project_id=project_id)

    def _save_record(self, record: ProjectAgentState) -> None:
        record.revision += 1
        record.history = record.history[-100:]
        atomic_model(self.service.root(record.project_id) / "agent-state.json", record)

    def _save_operation(self, operation: AgentOperation) -> None:
        operation.updated_at = time()
        atomic_model(self._path(operation.project_id, operation.id), operation)

    def _derive(self, project_id: str, prior: AgentState) -> AgentState:
        project = self.service.get_project(project_id)
        root = self.service.root(project_id)
        state = AgentState(budget=prior.budget, brief_confirmed=bool(project.brief),
                           candidate_count=len(project.candidates), compiled_count=len(project.candidates))
        if not project.candidates:
            return state
        state.phase = Phase.EVALUATE
        hashes = {spec_hash(candidate, root) for candidate in project.candidates}
        media = media_fingerprint(project.media)
        evidence_file = root / "eval-media.json"
        media_evidence = json.loads(evidence_file.read_text()) if evidence_file.exists() else {}
        valid = [evaluation for evaluation in project.evaluations
                 if evaluation.spec_hash in hashes and self.service.evaluation_is_current(project_id, evaluation)
                 and media_evidence.get(evaluation.spec_hash) == media
                 ]
        if not valid:
            return state
        evaluation = valid[-1]
        deployment_path = root / "deployment.json"
        deployment = Deployment.model_validate_json(deployment_path.read_text()) if deployment_path.exists() else None
        if deployment:
            evaluation = next((item for item in valid if item.spec_hash == deployment.spec_hash
                               and item.protocol_id == deployment.protocol_id), evaluation)
        state.record_evaluation(EvaluationEvidence(spec_hash=evaluation.spec_hash,
            dataset_hash=evaluation.dataset_hash, passed=evaluation.passed,
            sample_count=evaluation.sample_count, reviewed=True, protocol_id=evaluation.protocol_id,
            protocol_hash=evaluation.protocol_hash, promotion_eligible=evaluation.promotion_eligible))
        if (deployment and project.deployment_id == deployment.id and deployment.spec_hash == evaluation.spec_hash
                and deployment.protocol_id == evaluation.protocol_id):
            try:
                current = self.service.approved_deployment(project_id, deployment.candidate_index)
            except (ValueError, OSError):
                return state
            if current.approval_scope != "legacy":
                state.approve_deployment(spec_hash=deployment.spec_hash, dataset_hash=deployment.dataset_hash,
                    human_approved=True, override_reason=deployment.override_reason, protocol_id=deployment.protocol_id,
                    protocol_hash=deployment.protocol_hash, approval_scope=current.approval_scope)
        return state

    def _close(self, operation: AgentOperation, status: Literal["failed", "interrupted", "invalidated"], error: str) -> None:
        operation.status, operation.error = status, error
        for call in operation.calls:
            if call.status == "running":
                call.status, call.error, call.ended_ns = "interrupted", error, time_ns()
                self.platform.record_call(operation.project_id, operation.id, call, operation.state.phase)
                self.traces.emit(operation, call)
        operation.history.append(StateChange(action=status, phase=operation.state.phase.value, detail=error))
        self._save_operation(operation)
        self.platform.close(operation.project_id, operation.id, "stale" if status == "invalidated" else status, error)
        self.traces.emit(operation)

    def get(self, project_id: str) -> ProjectAgentState:
        return self.reconcile(project_id, "read")

    def reconcile(self, project_id: str, action: str = "change") -> ProjectAgentState:
        with self.repository.lock:
            record = self._record(project_id)
            if record.active_operation_id:
                operation = self.operation(project_id, record.active_operation_id)
                alive = True
                try:
                    os.kill(operation.owner_pid, 0)
                except ProcessLookupError:
                    alive = False
                if operation.status in {"running", "awaiting_commit"}:
                    if operation.input_fingerprint != self._fingerprint(project_id):
                        self._close(operation, "invalidated", "Project inputs changed during the agent operation")
                    elif time() > operation.deadline or (operation.status == "running" and not alive):
                        self._close(operation, "interrupted", "Agent owner exited or its operation deadline expired")
                if operation.status not in {"running", "awaiting_commit"}:
                    record.active_operation_id = None
                else:
                    record.state = operation.state
            if not record.active_operation_id:
                record.state = self._derive(project_id, record.state)
            project = self.service.get_project(project_id)
            record.brief = project.brief or record.brief
            record.clarification_count = project.clarification_count
            if action != "read":
                record.history.append(StateChange(action=action, phase=record.state.phase.value))
            self._save_record(record)
            return record

    def begin(self, project_id: str, brief: str, source_path: str, detector_model: str) -> AgentOperation:
        with self.repository.lock:
            record = self.get(project_id)
            if record.active_operation_id:
                raise AgentConflict("Another agent operation is active for this project")
            state = AgentState()
            state.confirm_brief(confirmed=True)
            operation = AgentOperation(id=uuid.uuid4().hex, project_id=project_id,
                trace_id=uuid.uuid4().hex, root_span_id=uuid.uuid4().hex[:16], owner_pid=os.getpid(),
                deadline=time() + state.budget.max_wall_seconds, input_fingerprint=self._fingerprint(project_id),
                brief=brief, source_path=source_path, detector_model=detector_model, state=state,
                history=[StateChange(action="begin", phase="plan")])
            self._save_operation(operation)
            record.active_operation_id = record.last_operation_id = operation.id
            record.state, record.brief = state, brief
            self._save_record(record)
            return operation

    def _active(self, project_id: str, operation_id: str) -> AgentOperation:
        record = self.get(project_id)
        if record.active_operation_id != operation_id:
            raise AgentConflict("Agent operation token is stale, interrupted, completed or belongs to another project")
        operation = self.operation(project_id, operation_id)
        if operation.status not in {"running", "awaiting_commit"}:
            raise AgentConflict("Agent operation is no longer active")
        return operation

    def record_decision(self, project_id: str, operation_id: str, decision: PlanDecision) -> AgentOperation:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.state.phase != Phase.PLAN:
                raise AgentConflict("A decision can only be recorded during planning")
            if operation.planning_options:
                selections = validate_model_choices(decision, operation.planning_options)
                validate_current_options(self.service, operation.planning_options, [item.capability_id for item in selections])
            elif any(choice.model_capability_id for choice in decision.choices):
                raise AgentConflict("Model selection requires a captured capability snapshot")
            operation.decision = decision
            self._save_operation(operation)
            return operation

    def record_options(self, project_id: str, operation_id: str, snapshot_id: str) -> AgentOperation:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.state.phase != Phase.PLAN or operation.decision is not None:
                raise AgentConflict("Capability options must be recorded before interpreting the goal")
            if any(call.kind == "llm" for call in operation.calls):
                raise AgentConflict("Capability options must be captured before the first model request")
            result = next((call.result for call in reversed(operation.calls) if call.name == "planning_options"
                           and call.status == "completed" and call.result and call.result.get("snapshot_id") == snapshot_id), None)
            if result is None:
                raise AgentConflict("Planning options must come from a captured engine tool result")
            options = PlanningOptions.model_validate(result)
            if options.project_id != project_id or (operation.planning_options and operation.planning_options != options):
                raise AgentConflict("The operation's capability snapshot cannot be replaced")
            if options.schema_version != "0.1" and (options.request_hash != request_hash(operation.brief)
                    or options.explicit_model_ids != explicit_model_ids(operation.brief, [str(item["id"]) for item in list_models()])):
                raise AgentConflict("Experimental model authorization must match this operation's originating user brief")
            validate_current_options(self.service, options, [])
            operation.planning_options = options
            self._save_operation(operation)
            return operation

    def planning_options(self, project_id: str, operation_id: str, detection_constraint: str | None = None) -> PlanningOptions:
        from engine.platform.planning_options import planning_options
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.state.phase != Phase.PLAN:
                raise AgentConflict("Planning options require the active planning operation")
            return planning_options(self.service, project_id, detection_constraint, request=operation.brief)

    def prepare_compile(self, project_id: str, operation_id: str, candidate_count: int) -> AgentOperation:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.decision is None or operation.state.phase != Phase.PLAN:
                raise AgentConflict("Record the typed planner decision before saving an executable plan")
            if operation.skills:
                self.record_skills(project_id, operation_id, operation.skills)
            regions = read_zone_state(self.service.root(project_id))
            selections = validate_model_choices(operation.decision, operation.planning_options) if operation.planning_options else []
            if operation.planning_options:
                validate_current_options(self.service, operation.planning_options, [item.capability_id for item in selections])
            proposal = plan_from_context(operation.decision, operation.brief, operation.source_path,
                operation.detector_model, {"zones_confirmed": regions.confirmed,
                    "saved_zone_ids": [zone.id for zone in regions.zones] if regions.confirmed else []}, operation.planning_options)
            if len(proposal.candidates) != candidate_count or proposal.questions:
                raise AgentConflict("The proposed candidates do not match the recorded complete decision")
            self.platform.publish(project_id, operation_id, operation.brief, proposal.candidates,
                                  Phase.COMPILE, "Initial typed proposal before compilation", skills=operation.skills,
                                  planning_options=operation.planning_options, model_selections=selections)
            operation.state.finish_plan(candidate_count)
            operation.history.append(StateChange(action="prepare_compile", phase="compile"))
            self._save_operation(operation)
            return operation

    def start_call(self, project_id: str, operation_id: str, kind: Literal["tool", "llm"],
                   name: str, request: dict[str, JsonValue]) -> CapturedCall:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.status != "running":
                raise AgentConflict("This operation is awaiting commit; it cannot execute more work")
            if any(call.status == "running" for call in operation.calls):
                raise AgentConflict("Another action is already in progress for this operation")
            if kind == "tool":
                operation.state.authorize_tool(name)
                if request.get("project_id", project_id) != project_id:
                    raise AgentConflict("A tool cannot access another project")
                if operation.state.phase == Phase.COMPILE:
                    self.platform.authorize(project_id, operation_id, operation.state.phase, name, request)
            else:
                if operation.state.phase != Phase.PLAN:
                    raise AgentConflict("Planner model requests are only allowed in the plan phase")
                operation.state.budget.consume_model()
            call = CapturedCall(id=uuid.uuid4().hex, kind=kind, name=name, started_ns=time_ns(), request=request)
            operation.calls.append(call)
            self.platform.record_call(project_id, operation_id, call, operation.state.phase)
            self._save_operation(operation)
            return call

    def finish_call(self, project_id: str, operation_id: str, call_id: str,
                    result: dict[str, JsonValue] | None, error: str | None = None) -> AgentOperation:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            call = next((item for item in operation.calls if item.id == call_id), None)
            if call is None or call.status != "running":
                raise AgentConflict("Call token is missing or already completed")
            call.result, call.error, call.ended_ns = result, error, time_ns()
            call.status = "failed" if error else "completed"
            self.platform.record_call(project_id, operation_id, call, operation.state.phase)
            self._save_operation(operation)
            self.traces.emit(operation, call)
            return operation

    def record_skills(self, project_id: str, operation_id: str, skills: list[SkillReference]) -> AgentOperation:
        from agent.skills import select_skills
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            expected = [item.reference for item in select_skills(operation.brief, self.service.get_project(project_id).use_case)]
            if operation.state.phase != Phase.PLAN or skills != expected:
                raise AgentConflict("Skill references must match the selected installed playbooks")
            operation.skills = skills
            self._save_operation(operation)
            return operation

    def stage(self, project_id: str, operation_id: str, result: PlanResult) -> AgentOperation:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if result.operation_id != operation.id or operation.decision is None:
                raise AgentConflict("Plan result is not bound to this operation's decision")
            regions = read_zone_state(self.service.root(project_id))
            expected = plan_from_context(operation.decision, operation.brief,
                operation.source_path, operation.detector_model, {
                    "zones_confirmed": regions.confirmed,
                    "saved_zone_ids": [zone.id for zone in regions.zones] if regions.confirmed else [],
                }, operation.planning_options)
            if (result.candidates != expected.candidates or result.questions != expected.questions
                    or result.needs_zones != expected.needs_zones or result.message != expected.message
                    or result.tool_calls != operation.state.budget.tool_calls):
                raise AgentConflict("Staged result does not match the recorded decision and tool budget")
            for candidate in result.candidates:
                payload = candidate.model_dump(mode="json", by_alias=True)
                validations = [call for call in operation.calls if call.name == "pipeline_validate"
                               and call.status == "completed" and call.request.get("spec") == payload
                               and call.result and call.result.get("valid") is True]
                previews = [call for call in operation.calls if call.name == "pipeline_run"
                            and call.status == "completed" and call.request.get("spec") == payload
                            and call.result and call.result.get("frames")]
                if not validations or not previews:
                    raise AgentConflict("Every candidate requires captured compiler success and a real sample preview")
            if result.candidates:
                operation.state.finish_compile(len(result.candidates))
            else:
                operation.state.phase = Phase.CLARIFY
            operation.result = result
            operation.status, operation.deadline = "awaiting_commit", time() + 30
            operation.history.append(StateChange(action="stage", phase=operation.state.phase.value))
            self._save_operation(operation)
            return operation

    def fail(self, project_id: str, operation_id: str, error: str) -> None:
        with self.repository.lock:
            operation = self.operation(project_id, operation_id)
            if operation.status in {"running", "awaiting_commit"}:
                self._close(operation, "failed", error)
                self.reconcile(project_id, "failure")

    def commit_plan(self, project_id: str, operation_id: str, result: PlanResult, user_prompt: str) -> Project:
        with self.repository.lock:
            operation = self._active(project_id, operation_id)
            if operation.status != "awaiting_commit" or operation.result != result or result.operation_id != operation.id:
                raise AgentConflict("Only the exact staged result may be committed with its operation token")
            project = self.service.get_project(project_id)
            clarifications = 0 if result.needs_zones else len(result.questions)
            if project.clarification_count + clarifications > 3:
                raise AgentConflict("The project's three-question budget is exhausted")
            if result.candidates:
                project = self.service.save_candidates(project_id, result.candidates, user_prompt)
            project.clarification_count += clarifications
            last_user = next((message.content for message in reversed(project.messages) if message.role == "user"), None)
            if last_user != user_prompt:
                project.messages.append(Message(role="user", content=user_prompt))
            project.messages.append(Message(role="assistant",
                content=result.message + ("\n" + "\n".join(result.questions) if result.questions else "")))
            self.repository.save(project)
            operation.status = "completed"
            self.platform.accept_effect(project_id, operation_id)
            self.platform.close(project_id, operation_id, "completed")
            operation.history.append(StateChange(action="commit", phase=operation.state.phase.value))
            self._save_operation(operation)
            self.traces.emit(operation)
            record = self._record(project_id)
            record.active_operation_id = None
            record.state = operation.state
            self._save_record(record)
            self.reconcile(project_id, "plan_committed")
            return project
