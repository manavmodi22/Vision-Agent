"""Application operations shared by the native API and MCP tool boundary."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from pydantic import JsonValue

from engine.eval import dataset_hash, evaluate, spec_hash
from engine.media import import_paths, media_fingerprint
from engine.runtime import run_pipeline
from engine.store.models import Deployment, EventRecord, Project, ReviewRecord
from engine.store.repository import Repository, atomic_model
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
        full = self.annotations(project_id)
        path = self.root(project_id) / "active-holdout.json"
        if not path.exists():
            return full
        holdout = EvalDataset.model_validate_json(path.read_text())
        names = {item.image_path for item in holdout.annotations}
        current = {item.image_path: item for item in full.annotations}
        selected = [current[item.image_path] for item in holdout.annotations if item.image_path in current]
        if len(selected) != len(names):
            raise ValueError("The frozen holdout is missing images; restore its annotations")
        return EvalDataset(id=holdout.id, annotations=selected)

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

    def evaluate(self, project_id: str, candidate_index: int = 0) -> EvaluationResult:
        with self.repository.lock:
            candidate = self.candidate(project_id, candidate_index)
            dataset = self.evaluation_annotations(project_id)
            if not 10 <= len(dataset.annotations) <= 50:
                raise ValueError("Evaluation requires 10–50 labelled images")
            if not all(annotation.reviewed for annotation in dataset.annotations):
                raise ValueError("Review every annotation before evaluating")
            project = self.get_project(project_id)
            fingerprint = media_fingerprint(project.media)
        result = evaluate(candidate, dataset, self.root(project_id))
        with self.repository.lock:
            project = self.get_project(project_id)
            if (spec_hash(self.candidate(project_id, candidate_index), self.root(project_id)) != result.spec_hash
                    or dataset_hash(self.evaluation_annotations(project_id), self.root(project_id)) != result.dataset_hash
                    or media_fingerprint(project.media) != fingerprint):
                raise ValueError("Project changed during evaluation; evaluate again")
            project.evaluations = [old for old in project.evaluations
                                   if old.spec_hash != result.spec_hash] + [result]
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

    def deploy(self, project_id: str, candidate_index: int, approved: bool,
               override_reason: str | None = None) -> dict[str, JsonValue]:
        with self.repository.lock:
            if not approved:
                raise ValueError("Deployment requires an explicit user approval")
            project = self.get_project(project_id)
            candidate = self.candidate(project_id, candidate_index)
            dataset = self.evaluation_annotations(project_id)
            current_hash = spec_hash(candidate, self.root(project_id))
            current_dataset = dataset_hash(dataset, self.root(project_id))
            result = next((item for item in project.evaluations
                           if item.spec_hash == current_hash and item.dataset_hash == current_dataset), None)
            if result is None:
                raise ValueError("Evaluate this pipeline on the current reviewed labels before deploying")
            if not all(item.reviewed for item in dataset.annotations):
                raise ValueError("Evaluation labels must be reviewed")
            evidence_path = self.root(project_id) / "eval-media.json"
            evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
            if evidence.get(current_hash) != media_fingerprint(project.media):
                raise ValueError("Media changed since evaluation; evaluate again")
            reason = override_reason.strip() if override_reason else None
            if not result.passed and (not reason or len(reason) < 10):
                raise ValueError("Target missed: enter an override reason of at least 10 characters")
            deployment = Deployment(id=uuid.uuid4().hex, candidate_index=candidate_index,
                                    spec_hash=current_hash, dataset_hash=current_dataset,
                                    override_reason=reason, synthetic=project.synthetic)
            atomic_model(self.root(project_id) / "deployment.json", deployment)
            project.deployment_id = deployment.id
            project.status = "ready"
            self.repository.save(project)
            return {"deployment_id": deployment.id, "status": "ready"}

    def run(self, project_id: str, candidate_index: int = 0, max_frames: int = 50,
            paths: list[str] | None = None) -> RunResult:
        from engine.evidence import persist_run

        with self.repository.lock:
            project = self.get_project(project_id)
            candidate = self.candidate(project_id, candidate_index)
            path = self.root(project_id) / "deployment.json"
            if not project.deployment_id or not path.exists():
                raise ValueError("Approve deployment before running and recording events")
            deployment = Deployment.model_validate_json(path.read_text())
            if (deployment.spec_hash != spec_hash(candidate, self.root(project_id))
                    or deployment.dataset_hash != dataset_hash(self.evaluation_annotations(project_id), self.root(project_id))
                    or deployment.id != project.deployment_id):
                raise ValueError("Approval is stale; evaluate and approve the current pipeline")
            evidence = json.loads((self.root(project_id) / "eval-media.json").read_text())
            source_fingerprint = media_fingerprint(project.media)
            if evidence.get(deployment.spec_hash) != source_fingerprint:
                raise ValueError("Media changed since approval; evaluate and approve again")
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
        with self.repository.lock:
            project = self.get_project(project_id)
            if (project.deployment_id != deployment.id
                    or spec_hash(self.candidate(project_id, candidate_index), self.root(project_id)) != deployment.spec_hash
                    or dataset_hash(self.evaluation_annotations(project_id), self.root(project_id)) != deployment.dataset_hash
                    or media_fingerprint(project.media) != source_fingerprint):
                raise ValueError("Project approval or evidence changed during run; results not persisted")
            if run_input_hash is not None and media_fingerprint(run_inputs) != run_input_hash:
                raise ValueError("Run input images changed during inference; results not persisted")
            if run_folder is not None:
                atomic_model(run_folder / "result.json", result)
                (run_folder / "provenance.json").write_text(json.dumps({
                    "deployment_id": deployment.id, "approved_spec_hash": deployment.spec_hash,
                    "evaluation_dataset_hash": deployment.dataset_hash, "input_hash": run_input_hash,
                    "source_mode": "new_media", "input_count": len(run_inputs)}, indent=2))
            rule_events = persist_run(self.repository, project, result)
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
