"""Human-only draft import: reserve, preview, CAS, then recoverable review adoption."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import Field, JsonValue

from engine.builds.store import BuildRecord, BuildStore
from engine.compiler import compile_pipeline
from engine.eval.hashes import file_hash, spec_hash
from engine.investigations.handoff_evidence import DraftEvidence, verify_draft
from engine.investigations.store import InvestigationConflict, InvestigationStore
from engine.runtime import run_pipeline
from engine.runtime.media import IMAGE_EXTENSIONS
from engine.service import WorkspaceService
from engine.store.models import Project, now
from engine.store.repository import atomic_model
from spec.build import HandoffResult, HandoffStatus
from spec.handoff import (
    AbortHandoff,
    AcceptHandoff,
    HandoffProposal,
    HandoffReceipt,
    PrepareHandoff,
)
from spec.investigation import RecordId
from spec.models import Contract, PipelineSpec, RunResult
from spec.planning import CandidateModelSelection, PlanningOptions


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class SavedProposal(Contract):
    proposal: HandoffProposal
    selection: PrepareHandoff
    project_before: Project
    external_fingerprint: str
    candidate: PipelineSpec
    options: PlanningOptions
    bindings: list[CandidateModelSelection]
    objective: str
    original_revision: dict[str, JsonValue]
    media_manifest: dict[str, str]

    def content_hash(self) -> str:
        value = self.model_dump(mode="json", by_alias=True)
        value["proposal"].pop("proposal_hash")
        return digest(value)


class Journal(Contract):
    task_id: RecordId
    proposal_id: RecordId
    status: Literal["prepared", "previewing", "committing", "completed", "interrupted", "aborting", "aborted"]
    receipt: HandoffReceipt | None = None
    preview: RunResult | None = None
    preview_input_refs: list[dict[str, JsonValue]] = Field(default_factory=list)
    project_after: Project | None = None
    error: str | None = None


class ReviewHandoff:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.store = InvestigationStore(service)
        self.builds = BuildStore(service)

    def _journal_path(self, project_id: str) -> Path:
        return self.service.root(project_id) / "review-handoff.json"

    def _save(self, project_id: str, journal: Journal) -> None:
        atomic_model(self._journal_path(project_id), journal)

    def _lock(self, project_id: str) -> FileLock:
        return FileLock(self.service.root(project_id) / ".review-handoff.lock", timeout=0)

    def _lifecycle(self, project_id: str) -> FileLock:
        folder = self.service.root(project_id) / "investigations"
        folder.mkdir(exist_ok=True)
        return FileLock(folder / ".lifecycle.lock", timeout=0, thread_local=False)

    def _read(self, project_id: str) -> Journal | None:
        path = self._journal_path(project_id)
        return Journal.model_validate_json(path.read_text()) if path.exists() else None

    def _proposal_path(self, project_id: str, task_id: str, proposal_id: str) -> Path:
        # IDs have already passed the request/journal DTO before filesystem use.
        return self.store.root(project_id, task_id) / "handoffs" / (proposal_id + ".json")

    def _proposal(self, project_id: str, journal: Journal) -> SavedProposal:
        saved = SavedProposal.model_validate_json(self._proposal_path(project_id, journal.task_id, journal.proposal_id).read_text())
        if (saved.proposal.project_id != project_id or saved.proposal.task_id != journal.task_id
                or saved.proposal.id != journal.proposal_id or saved.content_hash() != saved.proposal.proposal_hash):
            raise InvestigationConflict("Saved handoff proposal identity or content changed")
        return saved

    def _manifest(self, project_id: str) -> dict[str, str]:
        root, project = self.service.root(project_id), self.service.get_project(project_id)
        paths = [Path(path) if Path(path).is_absolute() else root / path for path in project.media]
        folder = root / "media"
        actual = {path.resolve() for path in folder.rglob("*") if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()}
        if (any(path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) for path in paths)
                or actual != {path.resolve() for path in paths}):
            raise InvestigationConflict("Imported media membership changed; reconcile project media before handoff")
        return {str(path.resolve()): file_hash(path) for path in sorted(paths)}

    def _external(self, project_id: str) -> str:
        root = self.service.root(project_id)
        names = ["annotations.json", "dataset-metadata.json", "active-holdout.json", "evaluation-configuration.json",
                 "deployment.json", "eval-media.json"]
        documents = {name: file_hash(root / name) if (root / name).exists() else None for name in names}
        documents.update({str(path.relative_to(root)): file_hash(path) for path in sorted((root / "zones").rglob("*.json"))})
        # Exposure logging is intentionally additive; the original membership,
        # labels, configuration, models and source bytes must remain unchanged.
        from engine.eval.protocol import stable_configuration_hash
        from engine.eval.recipe import recipe_hash
        return digest({"documents": documents, "media": self._manifest(project_id),
            "configuration": stable_configuration_hash(root, self.service.annotations(project_id)),
            "recipe": recipe_hash()})

    def _empty(self, project_id: str) -> Project:
        project, root = self.service.get_project(project_id), self.service.root(project_id)
        if project.candidates or project.evaluations or project.deployment_id or (root / "deployment.json").exists():
            raise InvestigationConflict("First draft import requires an empty application; existing work cannot be replaced")
        if (root / "build.json").exists():
            raise InvestigationConflict("An existing build must be resolved before importing this draft")
        for path in (root / "investigations").glob("*/task.json"):
            state = self.store.get(project_id, path.parent.name)
            if state.status == "running" or state.pending_action_id or state.pending_model_call_id:
                raise InvestigationConflict("An investigation is still active; finish it before importing a draft")
        return project

    def prepare(self, project_id: str, task_id: str, request: PrepareHandoff) -> HandoffProposal:
        with self._lock(project_id), self._lifecycle(project_id), self.service.repository.lock:
            prior = self._read(project_id)
            if prior and prior.status in {"previewing", "committing", "aborting"}:
                raise InvestigationConflict("Recover the previous handoff status before preparing another proposal")
            project = self._empty(project_id)
            evidence = verify_draft(self.service, self.store, project_id, task_id, request)
            state = self.store.get(project_id, task_id)
            candidate_hash = spec_hash(evidence.candidate, self.service.root(project_id))
            proposal = HandoffProposal(id=uuid.uuid4().hex, project_id=project_id, task_id=task_id,
                task_revision=request.expected_revision, workflow_revision_id=request.workflow_revision_id,
                preview_observation_id=request.preview_observation_id, proposal_hash="0" * 64,
                origin_task_status="draft_ready" if state.status == "draft_ready" else "inconclusive",
                origin_stop_reason=state.stop_reason,
                original_spec_hash=str(evidence.revision["spec_hash"]), candidate_spec_hash=candidate_hash,
                source_before=evidence.original.inputs["source"].path, original_media_count=len(evidence.revision["input_refs"]),
                project_media_count=len(project.media), candidate_name=evidence.candidate.name,
                metric=evidence.candidate.eval.metric, target=evidence.candidate.eval.target,
                limitations=["The source changes from frozen examples to imported project media; all other graph fields and model bindings are preserved.",
                    "Acceptance runs a new preview on up to five available development images. Reserved acceptance images are excluded.",
                    "Static crops remain static; layout changes need separate validation.",
                    "Review the proposed metric, target and labels. This import supplies no measured quality or deployment approval."],
                created_at=now())
            if state.status == "inconclusive":
                proposal.limitations.insert(0, "Investigation did not complete; this imports only its saved draft for review.")
            saved = SavedProposal(proposal=proposal, selection=request, project_before=project,
                external_fingerprint=self._external(project_id), candidate=evidence.candidate,
                options=evidence.options, bindings=evidence.bindings, objective=evidence.objective,
                original_revision=evidence.revision, media_manifest=self._manifest(project_id))
            saved.proposal.proposal_hash = saved.content_hash()
            atomic_model(self._proposal_path(project_id, task_id, proposal.id), saved)
            self._save(project_id, Journal(task_id=task_id, proposal_id=proposal.id, status="prepared"))
            return saved.proposal

    def _current(self, project_id: str, saved: SavedProposal, *, after: Project | None = None) -> DraftEvidence:
        project = self.service.get_project(project_id)
        if project != saved.project_before and project != after:
            raise InvestigationConflict("Project changed since the handoff proposal; no changes were overwritten")
        if self._external(project_id) != saved.external_fingerprint:
            raise InvestigationConflict("Media, labels or evaluation configuration changed since the proposal")
        evidence = verify_draft(self.service, self.store, project_id, saved.proposal.task_id, saved.selection)
        if (evidence.candidate != saved.candidate or evidence.options != saved.options or evidence.bindings != saved.bindings
                or spec_hash(saved.candidate, self.service.root(project_id)) != saved.proposal.candidate_spec_hash):
            raise InvestigationConflict("Workflow/model evidence changed since the handoff proposal")
        return evidence

    def accept(self, project_id: str, task_id: str, request: AcceptHandoff) -> HandoffResult:
        with self._lock(project_id), self._lifecycle(project_id):
            with self.service.repository.lock:
                journal = self._read(project_id)
                if journal is None or journal.task_id != task_id or journal.proposal_id != request.proposal_id:
                    raise InvestigationConflict("Prepare the current draft before accepting its handoff")
                saved = self._proposal(project_id, journal)
                if request.proposal_hash != saved.proposal.proposal_hash:
                    raise InvestigationConflict("The reviewed proposal hash does not match")
                if journal.receipt and journal.receipt.client_request_id != request.client_request_id:
                    raise InvestigationConflict("This handoff already has a different idempotency key; read its status")
                if journal.status == "committing":
                    self._commit(project_id, journal, saved)
                if journal.status == "completed":
                    return self._result(project_id, journal)
                if journal.status != "prepared":
                    raise InvestigationConflict("The earlier preview outcome is uncertain or failed. Read status and explicitly prepare a new proposal; it will not repeat automatically")
                self._empty(project_id)
                self._current(project_id, saved)
                journal.receipt = HandoffReceipt(id=uuid.uuid4().hex, project_id=project_id, task_id=task_id,
                    workflow_revision_id=saved.proposal.workflow_revision_id, preview_observation_id=saved.proposal.preview_observation_id,
                    proposal_id=saved.proposal.id, proposal_hash=saved.proposal.proposal_hash,
                    client_request_id=request.client_request_id, build_id=uuid.uuid4().hex,
                    original_spec_hash=saved.proposal.original_spec_hash, candidate_spec_hash=saved.proposal.candidate_spec_hash,
                    origin_task_status=saved.proposal.origin_task_status, origin_stop_reason=saved.proposal.origin_stop_reason,
                    created_at=now())
                journal.status = "previewing"
                self._save(project_id, journal)  # Durable reservation precedes any actual inference.
            try:
                preview = run_pipeline(saved.candidate, self.service.root(project_id), max_frames=5)
                self._validate_preview(project_id, saved, preview)
                with self.service.repository.lock:
                    self._current(project_id, saved)
                    after = saved.project_before.model_copy(deep=True)
                    after.candidates, after.brief, after.status = [saved.candidate], saved.objective, "building"
                    after.evaluations, after.deployment_id, after.approval_scope, after.trial_limits = [], None, None, {}
                    after.updated_at = now()
                    journal.preview, journal.project_after, journal.status = preview, after, "committing"
                    journal.preview_input_refs = [{"image_path": frame.image_path, "source_sha256": frame.source_image_sha256}
                                                  for frame in preview.frames]
                    self._save(project_id, journal)  # Fully captured result; recovery only repeats document writes.
                    self._commit(project_id, journal, saved)
                    return self._result(project_id, journal)
            except Exception as error:
                if journal.status == "previewing":
                    journal.status, journal.error = "interrupted", str(error)[:1500]
                    with self.service.repository.lock:
                        self._save(project_id, journal)
                raise

    def _validate_preview(self, project_id: str, saved: SavedProposal, preview: RunResult) -> None:
        if not preview.frames or len(preview.frames) > 5:
            raise InvestigationConflict("Handoff requires an actual bounded development preview")
        compiled = compile_pipeline(saved.candidate, self.service.root(project_id))
        for frame in preview.frames:
            if saved.media_manifest.get(str(Path(frame.image_path).resolve())) != frame.source_image_sha256:
                raise InvestigationConflict("New preview input is outside the proposed source manifest")
            if (len(frame.inferences) != len(saved.bindings)
                    or {row.block_id for row in frame.inferences} != {row.block_id for row in saved.bindings}):
                raise InvestigationConflict("New preview did not execute the exact model bindings")
            for row in frame.inferences:
                if row.result.identity.identity_hash != compiled.inference_identities[row.block_id].identity_hash:
                    raise InvestigationConflict("New preview model identity changed")

    def _commit(self, project_id: str, journal: Journal, saved: SavedProposal) -> None:
        if journal.status != "committing" or journal.receipt is None or journal.project_after is None or journal.preview is None:
            raise InvestigationConflict("Incomplete handoff commit reservation")
        self._current(project_id, saved, after=journal.project_after)
        self._validate_preview(project_id, saved, journal.preview)
        root = self.service.root(project_id)
        # The empty-app restriction means there is no prior approval to preserve.
        # Pending handoffs block build continuation, evaluation and deployment.
        atomic_model(root / "project.json", journal.project_after)
        self.builds.adopt_investigation(journal.receipt, saved.objective, saved.candidate,
                                       journal.preview, saved.options, saved.bindings)
        receipt_path = self.store.root(project_id, journal.task_id) / "handoffs" / (journal.proposal_id + ".receipt.json")
        if receipt_path.exists() and HandoffReceipt.model_validate_json(receipt_path.read_text()) != journal.receipt:
            raise InvestigationConflict("Immutable handoff receipt changed")
        atomic_model(receipt_path, journal.receipt)
        journal.status = "completed"
        self._save(project_id, journal)

    def _result(self, project_id: str, journal: Journal) -> HandoffResult:
        assert journal.receipt is not None
        return HandoffResult(receipt=journal.receipt,
            build=self.builds.public(self.builds.get(project_id, journal.receipt.build_id)))

    def _abort(self, project_id: str, journal: Journal, saved: SavedProposal) -> None:
        if journal.receipt is None or journal.project_after is None:
            raise InvestigationConflict("No captured incomplete commit can be discarded")
        project, root = self.service.get_project(project_id), self.service.root(project_id)
        if project not in [saved.project_before, journal.project_after]:
            raise InvestigationConflict("Project edits differ from the incomplete import; discard cannot overwrite them. Restore or reconcile those edits first.")
        build_path = root / "build.json"
        if build_path.exists():
            record = BuildRecord.model_validate_json(build_path.read_text())
            if record.view.id != journal.receipt.build_id or record.view.investigation_origin != journal.receipt:
                raise InvestigationConflict("A different active build cannot be removed by discard")
        journal.status = "aborting"
        self._save(project_id, journal)
        atomic_model(root / "project.json", saved.project_before)
        build_path.unlink(missing_ok=True)
        self.builds.platform.close(project_id, journal.receipt.build_id, "failed", "Human discarded an incomplete draft import; immutable evidence is retained.")
        journal.status, journal.error = "aborted", "Incomplete import discarded. Original investigation and captured evidence are retained. Review current inputs and prepare a new proposal explicitly."
        self._save(project_id, journal)

    def abort(self, project_id: str, task_id: str, request: AbortHandoff) -> HandoffStatus:
        with self._lock(project_id), self._lifecycle(project_id), self.service.repository.lock:
            journal = self._read(project_id)
            if journal is None or journal.task_id != task_id or journal.proposal_id != request.proposal_id:
                raise InvestigationConflict("Discard requires the current incomplete handoff")
            saved = self._proposal(project_id, journal)
            if saved.proposal.proposal_hash != request.proposal_hash:
                raise InvestigationConflict("The reviewed proposal hash does not match")
            if journal.status not in {"committing", "aborting", "aborted"}:
                raise InvestigationConflict("Only an incomplete commit can be discarded; completed applications are preserved")
            if journal.status != "aborted":
                self._abort(project_id, journal, saved)
            return HandoffStatus(status="interrupted", proposal=saved.proposal, message=journal.error)

    def status(self, project_id: str, task_id: str) -> HandoffStatus:
        self.store.get(project_id, task_id)
        lock = self._lock(project_id)
        try:
            lock.acquire()
        except Timeout:
            with self.service.repository.lock:
                journal = self._read(project_id)
            if journal is None or journal.task_id != task_id:
                return HandoffStatus(status="none")
            return HandoffStatus(status="committing", proposal=self._proposal(project_id, journal).proposal,
                                 message="The handoff preview or commit is still in progress")
        try:
            with self._lifecycle(project_id), self.service.repository.lock:
                journal = self._read(project_id)
                if journal is None or journal.task_id != task_id:
                    return HandoffStatus(status="none")
                saved = self._proposal(project_id, journal)
                if journal.status == "previewing":
                    journal.status, journal.error = "interrupted", "The preview owner stopped before capturing its result. Inference will not be repeated automatically."
                    self._save(project_id, journal)
                if journal.status == "committing":
                    try:
                        self._commit(project_id, journal, saved)
                    except (ValueError, OSError) as error:
                        return HandoffStatus(status="conflict", proposal=saved.proposal, can_abort=True,
                            message="Captured import cannot be completed: " + str(error)[:1000] + ". Restore the exact evidence or explicitly discard this incomplete import.")
                if journal.status == "aborting":
                    self._abort(project_id, journal, saved)
                result = HandoffStatus.model_validate({"status": "interrupted" if journal.status in {"aborted", "aborting"} else journal.status,
                    "proposal": saved.proposal, "receipt": journal.receipt if journal.status == "completed" else None,
                    "message": journal.error})
                if journal.status == "completed" and journal.receipt:
                    current = self.builds.get(project_id)
                    if current.view.id == journal.receipt.build_id:
                        result.build = self.builds.public(current)
                    else:
                        result.message = "A later build superseded this imported draft; its receipt remains available."
                return result
        finally:
            lock.release()
