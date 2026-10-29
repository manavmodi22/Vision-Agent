"""Atomic A0 task ledger: reserve before effects and never replay unknown work."""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, TypeAdapter

from engine.service import WorkspaceService
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.investigation import (
    ActionReceipt,
    AskUser,
    BuilderDecision,
    ConstructWorkflow,
    Finish,
    InspectObservation,
    InvestigationBudget,
    ModelCall,
    NextAction,
    Observation,
    ObservationStatus,
    PrepareWorkflow,
    RunProbe,
    TaskState,
    WorkflowDecision,
    WorkflowPreviewEvidence,
)
from spec.models import Contract


class InvestigationConflict(ValueError):
    """A stale or uncaptured action must not execute."""


class InvestigationBudgetExceeded(ValueError):
    """Persistent action/model/probe allowance has been consumed."""


class InvestigationRecord(Contract):
    task: TaskState
    model_calls: list[ModelCall] = Field(default_factory=list)
    actions: list[ActionReceipt] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)


def _bounded(value: dict[str, JsonValue], maximum: int = 4 * 1024 * 1024) -> None:
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > maximum:
        raise ValueError("Investigation payload exceeds its storage bound; return artifact references or a bounded page")


def _elapsed(started: str, ended: str) -> float:
    return max(0.0, (datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds())


class InvestigationStore:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def _path(self, project_id: str, task_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", task_id):
            raise ValueError("Invalid investigation identifier")
        return self.service.root(project_id) / "investigations" / task_id / "task.json"

    def _load(self, project_id: str, task_id: str) -> InvestigationRecord:
        record = InvestigationRecord.model_validate_json(self._path(project_id, task_id).read_text())
        if record.task.id != task_id or record.task.project_id != project_id:
            raise InvestigationConflict("Stored investigation ownership does not match its path")
        return record

    def _save(self, record: InvestigationRecord) -> None:
        record.task.updated_at = now()
        atomic_model(self._path(record.task.project_id, record.task.id), record)

    @staticmethod
    def _running(record: InvestigationRecord) -> None:
        if record.task.status != "running":
            raise InvestigationConflict("Investigation is not running; resume or start a new task explicitly")

    def _exhausted(self, record: InvestigationRecord, reason: str) -> None:
        record.task.status, record.task.stop_reason = "inconclusive", reason
        record.task.revision += 1
        self._save(record)
        raise InvestigationBudgetExceeded(reason)

    def create(self, project_id: str, objective: str, budget: InvestigationBudget | None = None) -> TaskState:
        if not objective.strip():
            raise ValueError("Describe an investigation objective")
        allowance = (budget or InvestigationBudget()).model_copy(deep=True)
        if allowance.model_calls or allowance.actions or allowance.probes or allowance.elapsed_s:
            raise ValueError("A new task budget cannot contain consumed counters")
        with self.service.repository.lock:
            self.service.get_project(project_id)
            task = TaskState(id=uuid.uuid4().hex, project_id=project_id, objective=objective,
                budget=allowance, created_at=now(), updated_at=now())
            self._save(InvestigationRecord(task=task))
            return task

    def get(self, project_id: str, task_id: str) -> TaskState:
        with self.service.repository.lock:
            return self._load(project_id, task_id).task

    def root(self, project_id: str, task_id: str) -> Path:
        self.get(project_id, task_id)
        return self._path(project_id, task_id).parent

    def observations(self, project_id: str, task_id: str) -> list[Observation]:
        with self.service.repository.lock:
            return self._load(project_id, task_id).observations

    def get_observation(self, project_id: str, task_id: str, observation_id: str) -> Observation:
        for observation in self.observations(project_id, task_id):
            if observation.id == observation_id:
                return observation
        raise InvestigationConflict("Observation does not belong to this investigation")

    def actions(self, project_id: str, task_id: str) -> list[ActionReceipt]:
        with self.service.repository.lock:
            return self._load(project_id, task_id).actions

    def model_calls(self, project_id: str, task_id: str) -> list[ModelCall]:
        with self.service.repository.lock:
            return self._load(project_id, task_id).model_calls

    def start_model_call(self, project_id: str, task_id: str, context: dict[str, JsonValue], model: str,
                         visible_observation_ids: list[str] | None = None) -> ModelCall:
        _bounded(context, 1024 * 1024)
        if not model.strip():
            raise ValueError("Model identity or configured alias is required")
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            self._running(record)
            task = record.task
            if task.pending_action_id or task.pending_model_call_id:
                raise InvestigationConflict("An action or model call is already pending")
            if task.budget.elapsed_s >= task.budget.max_elapsed_s:
                self._exhausted(record, "Investigation elapsed-time budget exhausted")
            if task.budget.model_calls >= task.budget.max_model_calls:
                self._exhausted(record, "Investigation model-call budget exhausted")
            exposed = task.latest_observation_ids if visible_observation_ids is None else visible_observation_ids
            if not set(exposed) <= {item.id for item in record.observations}:
                raise InvestigationConflict("Model context references an unknown observation")
            call = ModelCall(id=uuid.uuid4().hex, state_revision=task.revision, model=model,
                context=context, visible_observation_ids=exposed, started_at=now())
            record.model_calls.append(call)
            task.pending_model_call_id = call.id
            task.budget.model_calls += 1
            self._save(record)
            return call

    def finish_model_call(self, project_id: str, task_id: str, call_id: str,
                          response: dict[str, JsonValue] | None = None, error: str | None = None) -> ModelCall:
        if response is None and error is None:
            raise ValueError("Capture a model response or an explicit error")
        if response is not None:
            _bounded(response)
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            call = next((item for item in record.model_calls if item.id == call_id), None)
            if call is None:
                raise InvestigationConflict("Unknown model call")
            if call.status != "running":
                if call.status in {"completed", "failed"} and call.response == response and call.error == error:
                    return call
                raise InvestigationConflict("Model call is closed; late or changed responses are rejected")
            if record.task.pending_model_call_id != call_id:
                raise InvestigationConflict("Model call is not the pending attempt")
            call.response, call.error = response, error
            call.status, call.ended_at = ("failed" if error is not None else "completed"), now()
            record.task.budget.elapsed_s += _elapsed(call.started_at, call.ended_at)
            record.task.pending_model_call_id = None
            self._save(record)
            return call

    def reserve_action(self, project_id: str, task_id: str, decision: BuilderDecision) -> ActionReceipt:
        # Revalidate even if a caller has mutated a previously validated instance.
        decision = TypeAdapter(BuilderDecision).validate_python(decision.model_dump(mode="json"))
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            if not record.model_calls:
                raise InvestigationConflict("An action requires a captured model response")
            call = record.model_calls[-1]
            for receipt in record.actions:
                if receipt.model_call_id == call.id:
                    if receipt.decision == decision:
                        raise InvestigationConflict("Action is already reserved or closed; inspect its receipt instead of repeating effects")
                    raise InvestigationConflict("A captured model call cannot authorize a different action")
            self._running(record)
            task = record.task
            if task.pending_action_id or task.pending_model_call_id:
                raise InvestigationConflict("Another action or model call is pending")
            if task.budget.elapsed_s >= task.budget.max_elapsed_s:
                self._exhausted(record, "Investigation elapsed-time budget exhausted")
            if decision.state_revision != task.revision or call.state_revision != task.revision:
                raise InvestigationConflict("Action was proposed against a stale task revision")
            if call.status != "completed" or call.response is None:
                raise InvestigationConflict("An action requires a completed captured model response")
            captured = call.response.get("decision", call.response)
            if TypeAdapter(BuilderDecision).validate_python(captured) != decision:
                raise InvestigationConflict("Action differs from the captured model response")
            if (isinstance(decision, WorkflowDecision) and task.stage != "workflow") or (
                isinstance(decision, NextAction) and task.stage != "investigating"
            ):
                raise InvestigationConflict("Decision schema does not match the current investigation stage")
            known = {item.id for item in record.observations}
            exposed = {identifier for item in record.model_calls for identifier in item.visible_observation_ids}
            references = set(decision.based_on_observation_ids)
            if isinstance(decision.action, InspectObservation):
                references.add(decision.action.observation_id)
            elif isinstance(decision.action, (PrepareWorkflow, Finish, ConstructWorkflow)):
                references.update(decision.action.evidence_ids)
            if not references <= known:
                raise InvestigationConflict("Action references evidence outside this investigation")
            if not set(decision.based_on_observation_ids) <= exposed:
                raise InvestigationConflict("Action cites observations not exposed to the model")
            if isinstance(decision.action, Finish) and decision.action.outcome == "draft_ready":
                self._ready_revision(record, decision.action, exposed)
            if task.budget.actions >= task.budget.max_actions:
                self._exhausted(record, "Investigation action budget exhausted")
            probe = isinstance(decision.action, RunProbe)
            if probe and task.budget.probes >= task.budget.max_probes:
                self._exhausted(record, "Investigation probe budget exhausted")
            receipt = ActionReceipt(id=uuid.uuid4().hex, model_call_id=call.id, decision=decision, started_at=now())
            record.actions.append(receipt)
            task.pending_action_id = receipt.id
            task.budget.actions += 1
            task.budget.probes += int(probe)
            task.revision += 1
            self._save(record)
            return receipt

    @staticmethod
    def _preview_evidence(action: ConstructWorkflow, payload: dict[str, JsonValue]) -> WorkflowPreviewEvidence:
        evidence = WorkflowPreviewEvidence.model_validate({
            key: value for key, value in payload.items() if key in WorkflowPreviewEvidence.model_fields
        })
        if evidence.preview_media_ids != action.media_ids:
            raise InvestigationConflict("Preview media IDs differ from the reserved workflow request")
        return evidence

    @classmethod
    def _ready_revision(cls, record: InvestigationRecord, action: Finish, exposed: set[str]) -> None:
        task = record.task
        if task.selected_workflow_revision is None or action.workflow_revision_id != task.selected_workflow_revision:
            raise InvestigationConflict("draft_ready must select the current validated and previewed workflow revision")
        if task.preview_observation_id is None or task.preview_observation_id not in action.evidence_ids:
            raise InvestigationConflict("draft_ready must cite the selected workflow preview observation")
        if task.preview_observation_id not in exposed:
            raise InvestigationConflict("draft_ready preview evidence has not been exposed to the model")
        observation = next((item for item in record.observations if item.id == task.preview_observation_id), None)
        receipt = next((item for item in record.actions if observation and item.id == observation.action_id), None)
        if observation is None or observation.status != "completed" or receipt is None or not isinstance(receipt.action, ConstructWorkflow):
            raise InvestigationConflict("Selected workflow has no successful construction observation")
        evidence = cls._preview_evidence(receipt.action, observation.payload)
        if evidence.workflow_revision_id != action.workflow_revision_id:
            raise InvestigationConflict("Selected workflow revision differs from its preview evidence")

    def complete_action(self, project_id: str, task_id: str, action_id: str, payload: dict[str, JsonValue],
                        status: ObservationStatus = "completed",
                        error: dict[str, JsonValue] | str | None = None) -> Observation:
        _bounded(payload)
        if (status == "completed" and error is not None) or (status != "completed" and error is None):
            raise ValueError("Successful results cannot carry errors; failed/interrupted results require an error")
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            receipt = next((item for item in record.actions if item.id == action_id), None)
            if receipt is None:
                raise InvestigationConflict("Action was not reserved in this investigation")
            evidence = None
            if isinstance(receipt.action, ConstructWorkflow) and status == "completed":
                try:
                    evidence = self._preview_evidence(receipt.action, payload)
                except ValueError as exc:
                    status, error = "failed", {"code": "invalid_workflow_evidence", "message": str(exc)}
            if receipt.observation_id:
                observation = next(item for item in record.observations if item.id == receipt.observation_id)
                if (observation.payload, observation.status, observation.error) == (payload, status, error):
                    return observation
                raise InvestigationConflict("An existing observation cannot be replaced")
            self._running(record)
            if receipt.status != "reserved" or record.task.pending_action_id != action_id:
                raise InvestigationConflict("Action is closed or interrupted; discard any late result")
            observation = self._observe(record, receipt, payload, status, error)
            action = receipt.action
            if status == "completed":
                if isinstance(action, ConstructWorkflow) and evidence is not None:
                    record.task.selected_workflow_revision = evidence.workflow_revision_id
                    record.task.preview_observation_id = observation.id
                elif isinstance(action, AskUser):
                    record.task.status, record.task.question = "awaiting_input", action.question
                elif isinstance(action, Finish):
                    record.task.status, record.task.stop_reason = action.outcome, action.summary
                elif isinstance(action, PrepareWorkflow):
                    record.task.stage = "workflow"
            self._save(record)
            return observation

    @staticmethod
    def _observe(record: InvestigationRecord, receipt: ActionReceipt, payload: dict[str, JsonValue],
                 status: ObservationStatus, error: dict[str, JsonValue] | str | None) -> Observation:
        observation = Observation(id=uuid.uuid4().hex, action_id=receipt.id, result_type=receipt.action.type,
            status=status, payload=payload, error=error, created_at=now())
        record.observations.append(observation)
        receipt.status, receipt.observation_id, receipt.ended_at = status, observation.id, now()
        record.task.budget.elapsed_s += _elapsed(receipt.started_at, receipt.ended_at)
        record.task.pending_action_id = None
        if isinstance(receipt.action, ConstructWorkflow):
            record.task.stage = "investigating"
        record.task.latest_observation_ids = [observation.id]
        record.task.revision += 1
        return observation

    def _interrupt(self, record: InvestigationRecord, reason: str) -> bool:
        changed = False
        if record.task.pending_model_call_id:
            call = next(item for item in record.model_calls if item.id == record.task.pending_model_call_id)
            call.status, call.error, call.ended_at = "interrupted", reason, now()
            record.task.budget.elapsed_s += _elapsed(call.started_at, call.ended_at)
            record.task.pending_model_call_id = None
            changed = True
        if record.task.pending_action_id:
            receipt = next(item for item in record.actions if item.id == record.task.pending_action_id)
            self._observe(record, receipt, {"effect_status": "unknown", "automatic_retry": False}, "interrupted", reason)
            changed = True
        return changed

    def recover_pending(self, project_id: str, task_id: str) -> TaskState:
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            reason = "Interrupted pending work has unknown effects and will not be automatically repeated"
            if self._interrupt(record, reason):
                record.task.status, record.task.stop_reason = "interrupted", reason
                record.task.revision += 1
                self._save(record)
            return record.task

    def stop(self, project_id: str, task_id: str, reason: str,
             status: Literal["inconclusive", "cancelled", "failed", "paused", "interrupted"] = "inconclusive") -> TaskState:
        if not reason.strip():
            raise ValueError("A host stop needs an explicit reason")
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            self._interrupt(record, reason)
            if record.task.status != status or record.task.stop_reason != reason:
                record.task.status, record.task.stop_reason = status, reason
                record.task.revision += 1
            self._save(record)
            return record.task

    def resume(self, project_id: str, task_id: str, answer: str | None = None) -> TaskState:
        with self.service.repository.lock:
            record = self._load(project_id, task_id)
            task = record.task
            if task.status not in {"awaiting_input", "interrupted", "paused"}:
                raise InvestigationConflict("Only an awaiting-input, interrupted or explicitly paused task can resume")
            if task.pending_action_id or task.pending_model_call_id:
                raise InvestigationConflict("Recover pending work before resuming")
            if task.status == "awaiting_input" and (answer is None or not answer.strip()):
                raise ValueError("Answer the pending question before resuming")
            if answer is not None:
                if not answer.strip() or len(answer) > 8000:
                    raise ValueError("A clarification must contain 1–8000 characters")
                task.user_answers.append(answer)
            task.status, task.question, task.stop_reason = "running", None, None
            task.revision += 1
            self._save(record)
            return task
