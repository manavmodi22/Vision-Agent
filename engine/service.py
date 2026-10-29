"""Application operations shared by the native API and MCP tool boundary."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from engine.eval import dataset_hash, evaluate, spec_hash
from engine.media import import_paths, media_fingerprint
from engine.runtime import run_pipeline
from engine.store.models import Deployment, EventRecord, Project, ReviewRecord
from engine.store.repository import Repository, atomic_model
from spec.evaluation import EvaluationProtocol
from spec.models import (
    Annotation,
    EvalDataset,
    EvaluationResult,
    PipelineSpec,
    RunResult,
    SourceSpec,
)


class WorkspaceService:
    def __init__(self, data_dir: Path) -> None:
        self.repository = Repository(data_dir)

    def list_projects(self) -> list[Project]:
        return self.repository.list_projects()

    def get_project(self, project_id: str) -> Project:
        return self.repository.get(project_id)

    def create_project(self, name: str, use_case: str = "pallets") -> Project:
        if not name.strip() or len(name) > 120:
            raise ValueError("Project name must contain 1–120 characters")
        project = Project.model_validate({"id": uuid.uuid4().hex[:16], "name": name.strip(),
                                          "use_case": use_case})
        with self.repository.lock:
            self.repository.save(project)
            zone_path = self.root(project.id) / "zones" / "lanes.json"
            zone_path.parent.mkdir(exist_ok=True)
            zone_path.write_text(json.dumps({"zones": []}))
            atomic_model(self.root(project.id) / "annotations.json",
                         EvalDataset(id=f"{project.id}-v1", annotations=[]))
        return project

    def root(self, project_id: str) -> Path:
        self.get_project(project_id)
        return self.repository.project_root(project_id)

    def invalidate(self, project: Project) -> None:
        project.evaluations = []
        project.deployment_id = None
        project.approval_scope = None
        project.trial_limits = {}
        project.status = "building" if project.candidates else "draft"
        (self.root(project.id) / "deployment.json").unlink(missing_ok=True)
        (self.root(project.id) / "eval-media.json").unlink(missing_ok=True)

    def import_media(self, project_id: str, paths: list[str]) -> Project:
        with self.repository.lock:
            project = self.get_project(project_id)
            if project.fixture and project.media:
                raise ValueError("Create a separate project for real media; synthetic fixtures stay separate")
            remaining = 5000 - len(project.media)
            if remaining <= 0:
                raise ValueError("This dataset holds at most 5,000 images")
            imported = import_paths(paths, self.root(project_id) / "media", min(remaining, 500))
            project.media.extend(imported)
            self.invalidate(project)
            dataset = self.annotations(project_id)
            dataset.annotations.extend(Annotation(image_path=path, detections=[], reviewed=False)
                                       for path in imported)
            atomic_model(self.root(project_id) / "annotations.json", dataset)
            return self.repository.save(project)

    def demo(self, project_id: str) -> Project:
        from engine.runtime.fixtures import generate_demo

        with self.repository.lock:
            project = self.get_project(project_id)
            if project.media:
                raise ValueError("Synthetic walkthrough requires a new empty project")
            dataset = generate_demo(self.root(project_id))
            project.media = [str((self.root(project_id) / a.image_path).resolve())
                             if not Path(a.image_path).is_absolute() else a.image_path
                             for a in dataset.annotations]
            project.synthetic = True
            project.fixture = True
            project.data_origin = "Generated geometric fixtures; not warehouse imagery"
            atomic_model(self.root(project_id) / "annotations.json", dataset)
            self.invalidate(project)
            return self.repository.save(project)

    def candidate(self, project_id: str, index: int) -> PipelineSpec:
        project = self.get_project(project_id)
        if not 0 <= index < len(project.candidates):
            raise ValueError("Select an existing pipeline candidate")
        return project.candidates[index]

    def save_candidates(self, project_id: str, candidates: list[PipelineSpec], brief: str) -> Project:
        from engine.compiler import compile_pipeline

        with self.repository.lock:
            project = self.get_project(project_id)
            if not project.media:
                raise ValueError("Import sample images before building a pipeline")
            if not 1 <= len(candidates) <= 3:
                raise ValueError("A build must contain one to three candidates")
            for candidate in candidates:
                source = candidate.inputs["source"]
                if source.type != "image_folder" or (self.root(project_id) / source.path).resolve() != (self.root(project_id) / "media").resolve():
                    raise ValueError("App pipelines must use the imported project media folder")
                # Validate the actual model, graph and source before persisting the proposal.
                compile_pipeline(candidate, self.root(project_id))
                encoded = candidate.model_dump_json()
                if not project.fixture and "fixture-color-v1" in encoded:
                    raise ValueError("Fixture detector is only valid in the synthetic walkthrough")
            project.candidates = candidates
            project.brief = brief
            self.invalidate(project)
            return self.repository.save(project)

    def preview(self, project_id: str, candidate_index: int = 0) -> RunResult:
        return run_pipeline(self.candidate(project_id, candidate_index), self.root(project_id),
                            max_frames=5)

    def update_candidate(self, project_id: str, index: int, spec: PipelineSpec,
                         base_spec: PipelineSpec) -> Project:
        from engine.datasets import DatasetConflict

        with self.repository.lock:
            project = self.get_project(project_id)
            if self.candidate(project_id, index) != base_spec:
                raise DatasetConflict("Workflow changed since this draft was opened. Reload before saving.")
            candidates = list(project.candidates)
            candidates[index] = spec
            return self.save_candidates(project_id, candidates, project.brief)

    def propose_labels(self, project_id: str, candidate_index: int = 0,
                       max_frames: int = 50) -> EvalDataset:
        from engine.runtime.autolabel import propose_labels

        with self.repository.lock:
            root = self.root(project_id)
            candidate = self.candidate(project_id, candidate_index)
            dataset = self.annotations(project_id)
            before_dataset = dataset_hash(dataset, root)
            before_spec = spec_hash(candidate, root)
        proposal = propose_labels(candidate, dataset, root, max_frames=max_frames)
        with self.repository.lock:
            if (dataset_hash(self.annotations(project_id), root) != before_dataset
                    or spec_hash(self.candidate(project_id, candidate_index), root) != before_spec):
                raise ValueError("Labels or pipeline changed during inference; run suggestions again")
            return self.save_annotations(project_id, proposal)

    def annotations(self, project_id: str) -> EvalDataset:
        path = self.root(project_id) / "annotations.json"
        return EvalDataset.model_validate_json(path.read_text())

    def evaluation_annotations(self, project_id: str) -> EvalDataset:
        from engine.eval.protocol import read_configuration

        full = self.annotations(project_id)
        root = self.root(project_id)
        configuration = read_configuration(root, full)
        reserved = {(root / item.image_path).resolve() for item in configuration.images if item.split in {"acceptance", "train"}}
        validation = {(root / item.image_path).resolve() for item in configuration.images if item.split == "validation"}
        if validation:
            return EvalDataset(id=full.id, annotations=[item for item in full.annotations if (root / item.image_path).resolve() in validation])
        path = self.root(project_id) / "active-holdout.json"
        if not path.exists():
            return full.model_copy(update={"annotations": [item for item in full.annotations if (root / item.image_path).resolve() not in reserved]})
        holdout = EvalDataset.model_validate_json(path.read_text())
        names = {item.image_path for item in holdout.annotations}
        current = {item.image_path: item for item in full.annotations}
        selected = [current[item.image_path] for item in holdout.annotations if item.image_path in current]
        if len(selected) != len(names):
            raise ValueError("The frozen holdout is missing images; restore its annotations")
        return EvalDataset(id=full.id, annotations=[item for item in selected if (root / item.image_path).resolve() not in reserved])

    def save_annotations(self, project_id: str, dataset: EvalDataset) -> EvalDataset:
        with self.repository.lock:
            project = self.get_project(project_id)
            allowed = {Path(path).resolve() for path in project.media}
            seen: set[Path] = set()
            if not dataset.annotations or len(dataset.annotations) > 5000:
                raise ValueError("Save between 1 and 5,000 annotations")
            for annotation in dataset.annotations:
                path = (self.root(project_id) / annotation.image_path).resolve()
                if path not in allowed or path in seen:
                    raise ValueError("Each annotation must refer to one unique imported image")
                seen.add(path)
            if seen != allowed:
                raise ValueError("Annotation edits must preserve every imported image")
            atomic_model(self.root(project_id) / "annotations.json", dataset)
            self.invalidate(project)
            self.repository.save(project)
            return dataset

    def freeze_evaluation(self, project_id: str, candidate_indices: list[int] | None = None,
                          purpose: Literal["validation", "acceptance"] = "validation") -> EvaluationProtocol:
        from engine.eval.protocol import freeze_protocol

        with self.repository.lock:
            project = self.get_project(project_id)
            indices = candidate_indices if candidate_indices is not None else list(range(len(project.candidates)))
            return freeze_protocol(self.root(project_id), self.annotations(project_id),
                                   project.candidates, indices, purpose)

    def validate_evaluation(self, project_id: str, result: EvaluationResult) -> None:
        from engine.eval.protocol import validate_evidence

        validate_evidence(self.root(project_id), self.annotations(project_id),
                          self.get_project(project_id).candidates, result)

    def evaluation_is_current(self, project_id: str, result: EvaluationResult) -> bool:
        try:
            self.validate_evaluation(project_id, result)
        except (ValueError, OSError):
            return False
        return True

    def current_acceptance(self, project_id: str, candidate_index: int) -> EvaluationResult | None:
        current = spec_hash(self.candidate(project_id, candidate_index), self.root(project_id))
        return next((score for score in reversed(self.get_project(project_id).evaluations)
                     if score.spec_hash == current and score.evidence_scope == "acceptance"
                     and self.evaluation_is_current(project_id, score)), None)

    def evaluate(self, project_id: str, candidate_index: int = 0,
                 protocol_id: str | None = None) -> EvaluationResult:
        from engine.eval.protocol import protocol_dataset, read_protocol

        with self.repository.lock:
            root = self.root(project_id)
            candidate = self.candidate(project_id, candidate_index)
            protocol = (read_protocol(root, protocol_id) if protocol_id else
                        self.freeze_evaluation(project_id, [candidate_index]))
            if not any(item.candidate_index == candidate_index and item.spec_hash == spec_hash(candidate, root)
                       for item in protocol.candidates):
                raise ValueError("The candidate differs from the frozen evaluation protocol")
            full_dataset = self.annotations(project_id)
            dataset = protocol_dataset(root, full_dataset, protocol)
            if not 10 <= len(dataset.annotations) <= 50:
                raise ValueError("Evaluation requires 10–50 labelled images")
            if not all(annotation.reviewed for annotation in dataset.annotations):
                raise ValueError("Review every annotation before evaluating")
            project = self.get_project(project_id)
            fingerprint = media_fingerprint(project.media)
            result_path = root / "evaluation" / "results" / f"{protocol.id}-{candidate_index}.json"
            if result_path.exists():
                cached = EvaluationResult.model_validate_json(result_path.read_text())
                self.validate_evaluation(project_id, cached)
                project.evaluations = [old for old in project.evaluations
                    if (old.spec_hash, old.evidence_scope) != (cached.spec_hash, cached.evidence_scope)] + [cached]
                if not project.deployment_id:
                    project.status = "evaluated" if cached.passed else "needs_review"
                self.repository.save(project)
                evidence_path = root / "eval-media.json"
                evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
                evidence[cached.spec_hash] = fingerprint
                temporary = evidence_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(evidence))
                temporary.replace(evidence_path)
                return cached
        result = evaluate(candidate, full_dataset, root, protocol=protocol)
        with self.repository.lock:
            project = self.get_project(project_id)
            self.validate_evaluation(project_id, result)
            if media_fingerprint(project.media) != fingerprint:
                raise ValueError("Project changed during evaluation; evaluate again")
            if result_path.exists():
                if EvaluationResult.model_validate_json(result_path.read_text()) != result:
                    raise ValueError("A result already exists for this immutable evaluation protocol")
            else:
                atomic_model(result_path, result)
            project.evaluations = [old for old in project.evaluations
                                   if (old.spec_hash, old.evidence_scope) != (result.spec_hash, result.evidence_scope)] + [result]
            project.status = "evaluated" if result.passed else "needs_review"
            self.repository.save(project)
            # Atomic replace; no caller-supplied evidence can create this record.
            path = self.root(project_id) / "eval-media.json"
            evidence = json.loads(path.read_text()) if path.exists() else {}
            evidence[result.spec_hash] = fingerprint
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(evidence))
            temporary.replace(path)
        return result

    def approved_deployment(self, project_id: str, candidate_index: int) -> Deployment:
        """Revalidate current protocol-bound human approval without granting one."""
        project, root = self.get_project(project_id), self.root(project_id)
        path = root / "deployment.json"
        if not project.deployment_id or not path.is_file():
            raise ValueError("Approve deployment before running and recording events")
        deployment = Deployment.model_validate_json(path.read_text())
        if deployment.approval_scope == "legacy" or not deployment.protocol_id or not deployment.protocol_hash:
            raise ValueError("Legacy approval needs reevaluation and explicit current approval before recording")
        if (deployment.id != project.deployment_id or deployment.candidate_index != candidate_index
                or deployment.spec_hash != spec_hash(self.candidate(project_id, candidate_index), root)):
            raise ValueError("Approval is stale; evaluate and approve the current pipeline")
        score = next((item for item in project.evaluations
                      if item.spec_hash == deployment.spec_hash and item.dataset_hash == deployment.dataset_hash
                      and item.protocol_id == deployment.protocol_id and item.protocol_hash == deployment.protocol_hash), None)
        if score is None:
            raise ValueError("Approval evaluation is unavailable; evaluate and approve again")
        self.validate_evaluation(project_id, score)
        if deployment.approval_scope == "promotion" and (not score.passed or not score.promotion_eligible):
            raise ValueError("Approval has no eligible independent acceptance evidence")
        if deployment.approval_scope == "local_trial" and (not deployment.override_reason or len(deployment.override_reason.strip()) < 10):
            raise ValueError("A local trial requires explicit current consent and a reason")
        evidence_path = root / "eval-media.json"
        evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {}
        if evidence.get(deployment.spec_hash) != media_fingerprint(project.media):
            raise ValueError("Media changed since approval; evaluate and approve again")
        return deployment

    def deploy(self, project_id: str, candidate_index: int, approved: bool,
               override_reason: str | None = None, *,
               approval_scope: Literal["promotion", "local_trial"] = "promotion") -> dict[str, JsonValue]:
        with self.repository.lock:
            if not approved:
                raise ValueError("Deployment requires an explicit user approval")
            project, root = self.get_project(project_id), self.root(project_id)
            current_hash = spec_hash(self.candidate(project_id, candidate_index), root)
            scores = [item for item in reversed(project.evaluations)
                      if item.spec_hash == current_hash and self.evaluation_is_current(project_id, item)]
            if not scores:
                raise ValueError("Evaluate this pipeline under a current protocol on reviewed labels before deploying")
            reason = override_reason.strip() if override_reason else None
            if approval_scope == "promotion":
                result = next((item for item in scores if item.evidence_scope == "acceptance"
                               and item.passed and item.promotion_eligible), None)
                if result is None:
                    raise ValueError("Promotion requires passing independent acceptance evidence. Configure reserved acceptance groups or explicitly approve a bounded local trial.")
            elif approval_scope == "local_trial":
                if not reason or len(reason) < 10:
                    raise ValueError("A bounded local trial requires an explicit reason of at least 10 characters, even when the numeric target passes")
                result = scores[0]
            else:
                raise ValueError("Choose promotion or local_trial approval scope")
            limits = {"max_frames_per_run": 500, "max_live_duration_s": 3600} if approval_scope == "local_trial" else {}
            deployment = Deployment(id=uuid.uuid4().hex, candidate_index=candidate_index,
                spec_hash=current_hash, dataset_hash=result.dataset_hash, override_reason=reason,
                synthetic=project.synthetic, protocol_id=result.protocol_id, protocol_hash=result.protocol_hash,
                approval_scope=approval_scope, trial_limits=limits)
            atomic_model(root / "deployment.json", deployment)
            project.deployment_id, project.approval_scope, project.trial_limits = deployment.id, approval_scope, limits
            project.status = "ready"
            self.repository.save(project)
            return {"deployment_id": deployment.id, "status": "ready", "approval_scope": approval_scope,
                    "trial_limits": {key: value for key, value in limits.items()},
                    "protocol_id": deployment.protocol_id, "protocol_hash": deployment.protocol_hash,
                    "temporal_event_quality_measured": False,
                    "external_delivery_enabled_by_approval": approval_scope == "promotion"}

    def run(self, project_id: str, candidate_index: int = 0, max_frames: int = 50,
            paths: list[str] | None = None) -> RunResult:
        from engine.evidence import persist_run

        if not 1 <= max_frames <= 500:
            raise ValueError("Recorded runs are bounded to 1–500 frames")
        with self.repository.lock:
            project = self.get_project(project_id)
            candidate = self.candidate(project_id, candidate_index)
            deployment = self.approved_deployment(project_id, candidate_index)
            source_fingerprint = media_fingerprint(project.media)
        root = self.root(project_id)
        execution = candidate.model_copy(deep=True)
        run_folder: Path | None = None
        run_inputs: list[str] = []
        run_input_hash: str | None = None
        if paths is not None:
            if not paths or not 1 <= max_frames <= 500:
                raise ValueError("Select new media and a run limit from 1–500 frames")
            run_folder = root / "runs" / uuid.uuid4().hex
            run_inputs = import_paths(paths, run_folder / "media", max_frames)
            run_input_hash = media_fingerprint(run_inputs)
            execution.inputs["source"] = SourceSpec(type="image_folder", path=str((run_folder / "media").relative_to(root)))
            atomic_model(run_folder / "pipeline.json", execution)
        result = run_pipeline(execution, root, max_frames=max_frames)
        if deployment.approval_scope == "local_trial":
            result.warnings.append("Local trial: evidence is saved locally; external alert delivery is disabled.")
        with self.repository.lock:
            project = self.get_project(project_id)
            current_approval = self.approved_deployment(project_id, candidate_index)
            if current_approval != deployment or media_fingerprint(project.media) != source_fingerprint:
                raise ValueError("Project approval or evidence changed during run; results not persisted")
            if run_input_hash is not None and media_fingerprint(run_inputs) != run_input_hash:
                raise ValueError("Run input images changed during inference; results not persisted")
            if run_folder is not None:
                atomic_model(run_folder / "result.json", result)
                (run_folder / "provenance.json").write_text(json.dumps({
                    "deployment_id": deployment.id, "approved_spec_hash": deployment.spec_hash,
                    "approval_scope": deployment.approval_scope, "evaluation_protocol_id": deployment.protocol_id,
                    "evaluation_dataset_hash": deployment.dataset_hash, "input_hash": run_input_hash,
                    "source_mode": "new_media", "input_count": len(run_inputs)}, indent=2))
            rule_events = persist_run(self.repository, project, result, deployment)
            if deployment.approval_scope == "promotion":
                from engine.alerts.service import AlertService
                AlertService(self).enqueue_events(project_id, deployment.id, rule_events)
            project.status = "completed"
            self.repository.save(project)
        return result

    def events(self, project_id: str) -> list[EventRecord]:
        self.get_project(project_id)
        return self.repository.events(project_id)

    def review(self, project_id: str) -> list[ReviewRecord]:
        self.get_project(project_id)
        return self.repository.review(project_id)
