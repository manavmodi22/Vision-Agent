"""Bounded local training jobs. Restart records interruption, never success."""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout
from pydantic import Field, JsonValue

from engine.blocks.params import DetectParams
from engine.eval import dataset_hash, spec_hash
from engine.eval.protocol import (
    mark_usage,
    read_configuration,
    reserved_acceptance_paths,
    stable_configuration_hash,
)
from engine.models.local_manifest import local_model_path
from engine.models.manager import model_directory
from engine.platform.model_registration import register_user_candidate
from engine.service import WorkspaceService
from engine.store.models import Record, now
from engine.store.repository import atomic_model
from spec.models import EvalDataset, PipelineSpec


class Job(Record):
    id: str
    status: Literal["queued", "running", "completed", "failed", "interrupted"] = "queued"
    message: str = "Waiting for the local training worker"
    progress: float = Field(default=0, ge=0, le=1)
    created_at: str = Field(default_factory=now)
    result: dict[str, JsonValue] | None = None
    error: str | None = None


class JobManager:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.worker_lock = threading.Lock()
        self.threads: dict[str, threading.Thread] = {}
        # Another API process may still own the worker. Never mark its job dead.
        try:
            with FileLock(service.repository.root / ".training.lock", timeout=0):
                with service.repository.lock:
                    for path in service.repository.projects_dir.glob("*/jobs/*.json"):
                        job = Job.model_validate_json(path.read_text())
                        if job.status in {"queued", "running"}:
                            job.status = "interrupted"
                            job.error = "Engine stopped before training finished; start a new job"
                            job.message = job.error
                            atomic_model(path, job)
        except Timeout:
            pass

    def path(self, project_id: str, job_id: str) -> Path:
        if not job_id.isalnum() or len(job_id) != 32:
            raise ValueError("Invalid job identifier")
        return self.service.root(project_id) / "jobs" / f"{job_id}.json"

    def get(self, project_id: str, job_id: str) -> Job:
        return Job.model_validate_json(self.path(project_id, job_id).read_text())

    def start(self, project_id: str, candidate_index: int, max_minutes: float,
              epochs: int, approved: bool) -> Job:
        service = self.service
        if not approved:
            raise ValueError("Start training with an explicit user click")
        if not 0 < max_minutes <= 5 or not 1 <= epochs <= 30:
            raise ValueError("Training is limited to 5 minutes and 30 epochs per job")
        with service.repository.lock:
            project = service.get_project(project_id)
            if project.fixture:
                raise ValueError("Geometric fixtures cannot train a warehouse detector")
            dataset = service.annotations(project_id)
            if sum(a.reviewed for a in dataset.annotations) < 20:
                raise ValueError("Training needs at least 20 reviewed images, including 10 held out")
            candidate = service.candidate(project_id, candidate_index)
            if sum(block.type in {"detect", "detect_open_vocab"} for block in candidate.blocks) != 1:
                raise ValueError("Select a pipeline with exactly one detector before training")
            if len(project.candidates) >= 3:
                raise ValueError("Three candidates exist; build a fresh baseline before training")
            if not self.worker_lock.acquire(blocking=False):
                raise ValueError("A local training job is already active")
            lease = FileLock(service.repository.root / ".training.lock", timeout=0, thread_local=False)
            try:
                lease.acquire()
                job = Job(id=uuid.uuid4().hex)
                original_hash = dataset_hash(dataset, service.root(project_id))
                original_spec = spec_hash(candidate, service.root(project_id))
                original_configuration = stable_configuration_hash(service.root(project_id), dataset)
                atomic_model(self.path(project_id, job.id), job)
                worker = threading.Thread(target=self._run,
                    args=(project_id, job.id, candidate_index, candidate.model_copy(deep=True),
                          dataset, original_hash, original_spec, original_configuration, max_minutes, epochs, lease),
                    daemon=True, name=f"training-{job.id[:8]}")
                self.threads[job.id] = worker
                worker.start()
                return job
            except Exception as error:
                lease.release()
                self.worker_lock.release()
                if isinstance(error, Timeout):
                    raise ValueError("A local training job is already active in another process") from error
                raise

    def _run(self, project_id: str, job_id: str, candidate_index: int, candidate: PipelineSpec,
             dataset: EvalDataset, original_hash: str, original_spec: str,
             original_configuration: str,
             max_minutes: float, epochs: int, lease: FileLock) -> None:
        service = self.service
        job = Job(id=job_id)
        try:
            job = self.get(project_id, job_id)
            from engine.train import train_detector

            root = service.root(project_id)
            reserved = reserved_acceptance_paths(root, dataset)
            ordered = [item for item in dataset.annotations if item.reviewed and item.image_path not in reserved]
            with service.repository.lock:
                if (dataset_hash(service.annotations(project_id), root) != original_hash
                        or spec_hash(service.candidate(project_id, candidate_index), root) != original_spec
                        or stable_configuration_hash(root, service.annotations(project_id)) != original_configuration):
                    raise ValueError("Project changed before the approved training job started")
                configuration = read_configuration(root, dataset)
                if (root / "active-holdout.json").exists() or any(row.split == "validation" for row in configuration.images):
                    evaluation = service.evaluation_annotations(project_id)
                else:
                    evaluation = EvalDataset(id=dataset.id + "-heldout", annotations=ordered[-10:])
            holdout_names = {item.image_path for item in evaluation.annotations}
            declared_training = {(root / row.image_path).resolve() for row in configuration.images if row.split == "train"}
            training = EvalDataset(id=dataset.id + "-train", annotations=[item for item in ordered
                if item.image_path not in holdout_names and (not declared_training or (root / item.image_path).resolve() in declared_training)])
            detector = next(block for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"})
            requested_classes = DetectParams.model_validate(detector.params).classes
            available_classes = {d.label for item in training.annotations for d in item.detections}
            missing_classes = set(requested_classes) - available_classes
            if missing_classes:
                raise ValueError("Add reviewed training examples for the workflow classes: " + ", ".join(sorted(missing_classes)))
            atomic_model(root / "training-set.json", training)
            atomic_model(root / "heldout-set.json", evaluation)
            job.status, job.progress = "running", 0.1
            job.message = f"Training on {len(training.annotations)} reviewed images; {len(evaluation.annotations)} held out"
            atomic_model(self.path(project_id, job_id), job)
            model_id = "local-detector-" + job_id[:12]
            output_path = local_model_path(model_id, model_directory())
            if output_path.exists():
                raise ValueError("The training output already exists; no existing model registration was changed")
            expected_training_hash = dataset_hash(training, root)
            expected_evaluation_hash = dataset_hash(evaluation, root)
            selected_model = next(str(block.params.get("model", "")) for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"})
            from engine.train.validation import validate_training_data
            validate_training_data(training, evaluation, root)
            mark_usage(root, [item.image_path for item in training.annotations], "training")
            mark_usage(root, [item.image_path for item in evaluation.annotations], "training_validation")
            result = train_detector(training, evaluation, root, model_id,
                                    max_minutes=max_minutes, epochs=epochs,
                                    base_model_id=selected_model if selected_model.startswith("local-") else None)
            with service.repository.lock:
                if dataset_hash(service.annotations(project_id), root) != original_hash:
                    raise ValueError("Annotations changed during training; model saved but not attached")
                if spec_hash(service.candidate(project_id, candidate_index), root) != original_spec:
                    raise ValueError("Pipeline changed during training; model saved but not attached")
                if stable_configuration_hash(root, service.annotations(project_id)) != original_configuration:
                    raise ValueError("Evidence grouping or policy changed during training; model saved but not attached")
                registration = register_user_candidate(result, model_id, output_path,
                    expected_training_hash, expected_evaluation_hash, f"training-job:{project_id}:{job_id}")
                job.result = {"registration":registration}
                atomic_model(self.path(project_id, job_id), job)
                for block in candidate.blocks:
                    if block.type in {"detect", "detect_open_vocab"}:
                        block.type = "detect"
                        block.params["model"] = model_id
                        block.params["classes"] = list(requested_classes)
                candidate.name = f"Locally trained {model_id}"
                project = service.get_project(project_id)
                atomic_model(root / "active-holdout.json", evaluation)
                trained_index = len(project.candidates)
                trained_spec = spec_hash(candidate, root)
                holdout_fingerprint = dataset_hash(evaluation.model_copy(update={"id": dataset.id}), root)
                service.save_candidates(project_id, project.candidates + [candidate], project.brief)
            job.progress = 0.8
            job.message = "Scoring baseline and new candidate on the same held-out images"
            atomic_model(self.path(project_id, job_id), job)
            protocol = service.freeze_evaluation(project_id, [candidate_index, trained_index])
            baseline = service.evaluate(project_id, candidate_index, protocol.id)
            trained = service.evaluate(project_id, trained_index, protocol.id)
            if (baseline.spec_hash != original_spec or trained.spec_hash != trained_spec
                    or baseline.dataset_hash != holdout_fingerprint
                    or trained.dataset_hash != holdout_fingerprint):
                raise ValueError("Pipeline or held-out evidence changed during candidate comparison; score both again")
            job.status, job.progress = "completed", 1
            job.message = "Review held-out scores before choosing a candidate; deployment is unapproved."
            job.result = {"registration": registration, "training": result.model_dump(mode="json"),
                          "baseline": baseline.model_dump(mode="json"),
                          "trained": trained.model_dump(mode="json")}
        except Exception as error:
            job.status = "failed"
            job.message = "Training did not produce an evaluated candidate"
            job.error = f"{type(error).__name__}: {error}"
        finally:
            try:
                atomic_model(self.path(project_id, job_id), job)
            finally:
                lease.release()
                self.worker_lock.release()
