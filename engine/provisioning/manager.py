"""Durable bounded workers for explicitly approved fixed installation plans."""
from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
from filelock import FileLock, Timeout

from engine.provisioning.download import download_artifact
from engine.provisioning.plans import make_plan, plan_hash
from engine.provisioning.registry import RECIPES, recipe_for
from engine.provisioning.smoke import SmokeObservation
from engine.provisioning.state import (
    current_health,
    health_path,
    installation_hash,
    installation_matches,
    runtime_snapshot,
    target_path,
)
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.provisioning import (
    ProvisioningHealth,
    ProvisioningJob,
    ProvisioningJobRequest,
    ProvisioningOption,
    ProvisioningOptions,
    ProvisioningPlan,
    ProvisioningResult,
)


class ProvisioningConflict(ValueError):
    """A changed plan or concurrent install needs a new human decision."""


class ProvisioningManager:
    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "provisioning"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(self.root / ".state.lock")
        self.stopped = threading.Event()
        self.threads: list[threading.Thread] = []
        try:
            with FileLock(self.root / ".worker.lock", timeout=0):
                with self.lock:
                    for job in self.jobs():
                        if job.status in {"queued", "running"}:
                            job.status, job.phase = "interrupted", "interrupted"
                            job.error = "Engine stopped before completion. Review the current plan and explicitly retry."
                            job.message = job.error
                            self.save_job(job)
                            self._cleanup_interrupted_stage(job)
        except Timeout:
            pass

    def _cleanup_interrupted_stage(self, job: ProvisioningJob) -> None:
        root = target_path(recipe_for(job.model_id)).parent
        parent = root / ".provisioning-staging"
        if not root.is_dir() or not parent.is_dir() or parent.is_symlink():
            return
        try:
            with FileLock(root / ".provisioning.lock", timeout=0):
                stage = parent / job.id
                if stage.is_symlink():
                    stage.unlink()
                elif stage.is_dir():
                    shutil.rmtree(stage)
        except Timeout:
            pass  # Another process owns model installation; never clean its work.

    def path(self, group: str, identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid provisioning record identifier")
        return self.root / group / f"{identifier}.json"

    def options(self) -> ProvisioningOptions:
        rows = []
        for recipe in RECIPES.values():
            plan = make_plan(recipe)
            rows.append(ProvisioningOption(model_id=recipe.model_id, capability_id=plan.capability_id,
                name=recipe.name, action="blocked" if plan.blockers else plan.action,
                installed=plan.action == "validate", download_bytes=plan.total_download_bytes, blockers=plan.blockers))
        return ProvisioningOptions(options=rows)

    def create_plan(self, model_id: str) -> ProvisioningPlan:
        with self.lock:
            if len(list((self.root / "plans").glob("*.json"))) >= 1000:
                raise ValueError("Provisioning review history limit reached; retain/export history before creating more plans")
            plan = make_plan(recipe_for(model_id))
            atomic_model(self.path("plans", plan.id), plan)
            return plan

    def plan(self, identifier: str) -> ProvisioningPlan:
        plan = ProvisioningPlan.model_validate_json(self.path("plans", identifier).read_text())
        if plan.id != identifier or plan_hash(plan) != plan.plan_hash:
            raise ProvisioningConflict("Saved plan content changed; create and review a new plan")
        return plan

    def get(self, identifier: str) -> ProvisioningJob:
        return ProvisioningJob.model_validate_json(self.path("jobs", identifier).read_text())

    def jobs(self, model_id: str | None = None) -> list[ProvisioningJob]:
        if model_id:
            recipe_for(model_id)
        rows = [ProvisioningJob.model_validate_json(path.read_text()) for path in (self.root / "jobs").glob("*.json")]
        return sorted((row for row in rows if model_id is None or row.model_id == model_id), key=lambda row: row.created_at, reverse=True)

    def save_job(self, job: ProvisioningJob) -> None:
        job.updated_at = now()
        atomic_model(self.path("jobs", job.id), job)

    def _assert_plan_current(self, plan: ProvisioningPlan, *, target_changed: bool = False) -> None:
        recipe = recipe_for(plan.model_id)
        if (plan.runtime_snapshot != runtime_snapshot(recipe) or plan.target_directory != str(target_path(recipe))
                or plan.artifacts != list(recipe.artifacts)):
            raise ProvisioningConflict("Runtime, recipe or target changed; create and approve a new plan")
        if not target_changed and plan.existing_installation_hash != installation_hash(recipe):
            raise ProvisioningConflict("Installation changed since review; create and approve a new plan")
        if plan.blockers:
            raise ProvisioningConflict("This plan is blocked: " + "; ".join(plan.blockers))

    def start(self, request: ProvisioningJobRequest) -> ProvisioningJob:
        if not request.approved:
            raise ValueError("Installation and validation require an explicit human approval")
        with self.lock:
            if self.stopped.is_set():
                raise ProvisioningConflict("Provisioning worker is shutting down")
            plan = self.plan(request.plan_id)
            if request.plan_hash != plan.plan_hash:
                raise ProvisioningConflict("Approval does not match the immutable plan hash")
            previous = [row for row in self.jobs(plan.model_id) if row.plan_id == plan.id]
            for job in previous:
                if job.status in {"queued", "running"}:
                    return job
                if job.status == "completed":
                    self._assert_plan_current(plan, target_changed=True)
                    receipt = current_health(plan.model_id)
                    if receipt is not None and job.result and receipt.id == job.result.health_receipt_id:
                        return job
                    raise ProvisioningConflict("Completed installation evidence changed; review a new validation plan")
            self._assert_plan_current(plan)
            if len(self.jobs()) >= 1000:
                raise ValueError("Provisioning job history limit reached")
            lease = FileLock(self.root / ".worker.lock", timeout=0, thread_local=False)
            model_root = target_path(recipe_for(plan.model_id)).parent
            model_root.mkdir(parents=True, exist_ok=True)
            model_lease = FileLock(model_root / ".provisioning.lock", timeout=0, thread_local=False)
            try:
                lease.acquire()
                model_lease.acquire()
            except Timeout:
                lease.release()
                raise ProvisioningConflict("Another provisioning job is active; reopen its status instead") from None
            try:
                job = ProvisioningJob(id=uuid.uuid4().hex, plan_id=plan.id, plan_hash=plan.plan_hash,
                    model_id=plan.model_id, created_at=now(), updated_at=now(), total_bytes=plan.total_download_bytes)
                self.save_job(job)
                worker = threading.Thread(target=self._run, args=(job.model_copy(deep=True), lease, model_lease),
                    name="provision-" + job.id[:8], daemon=True)
                self.threads.append(worker)
                worker.start()
                return job
            except BaseException:
                model_lease.release()
                lease.release()
                raise

    def _smoke(self, model_id: str, deadline: float) -> dict[str, object]:
        remaining = min(100.0, deadline - time.monotonic())
        if remaining <= 0 or self.stopped.is_set():
            raise TimeoutError("Provisioning time budget expired before validation")
        environment = {key: value for key, value in os.environ.items() if key in {
            "PATH", "SYSTEMROOT", "TMPDIR", "TMP", "TEMP", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE"}}
        environment.update({"VISION_MODELS_DIR": str(target_path(recipe_for(model_id)).parent),
                            "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        # Fixed module and registry ID only. No shell, URL, expression or user path.
        process = subprocess.Popen([sys.executable, "-m", "engine.provisioning.smoke", model_id],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
        started = time.monotonic()
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            assert process.stdout is not None and process.stderr is not None
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    if self.stopped.is_set() or time.monotonic() - started >= remaining:
                        raise TimeoutError("Bounded black-image validation stopped or exceeded 100 seconds")
                    for key, _ in selector.select(timeout=min(.2, remaining)):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        buffers[key.data].extend(chunk)
                        if len(buffers[key.data]) > 65536:
                            raise ValueError("Validation output exceeded its diagnostic bound")
            if process.wait(timeout=1) != 0:
                raise ValueError("Black-image validation failed: " + buffers["stderr"].decode(errors="replace")[-2000:])
            return SmokeObservation.model_validate_json(bytes(buffers["stdout"])).model_dump(mode="json")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()

    def _run(self, initial: ProvisioningJob | str, lease: FileLock, model_lease: FileLock) -> None:
        job = initial.model_copy(deep=True) if isinstance(initial, ProvisioningJob) else None
        identifier = initial.id if isinstance(initial, ProvisioningJob) else initial
        stage: Path | None = None
        try:
            job = self.get(identifier)
            plan = self.plan(job.plan_id)
            recipe = recipe_for(plan.model_id)
            target = target_path(recipe)
            stage = target.parent / ".provisioning-staging" / identifier
            deadline = time.monotonic() + plan.max_duration_s
            self._assert_plan_current(plan)
            health_path(plan.model_id).unlink(missing_ok=True)
            job.status, job.phase = "running", "verifying"
            job.message = "Checking the approved plan and current installation"
            self.save_job(job)
            if plan.action == "install":
                if stage.parent.is_symlink() or stage.is_symlink():
                    raise ValueError("Staging directories cannot be symbolic links")
                stage.mkdir(parents=True, exist_ok=False, mode=0o700)
                completed = 0
                with httpx.Client(timeout=httpx.Timeout(connect=5, read=30, write=10, pool=5), trust_env=False, follow_redirects=False) as client:
                    for artifact in plan.artifacts:
                        job.phase = "downloading"
                        job.message = "Downloading " + artifact.filename + " from its reviewed official source"
                        self.save_job(job)
                        def progress(received: int, offset: int = completed) -> None:
                            job.downloaded_bytes = offset + received
                            job.progress = .75 * job.downloaded_bytes / max(1, job.total_bytes)
                            self.save_job(job)
                        download_artifact(artifact, stage / artifact.filename, deadline=deadline,
                                          stopped=self.stopped, progress=progress, client=client)
                        completed += artifact.expected_bytes
                job.phase, job.message, job.progress = "verifying", "Verified every downloaded byte count and SHA256", .8
                self.save_job(job)
                self._assert_plan_current(plan)
                if self.stopped.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("Provisioning stopped before atomic installation")
                (stage / "provenance.json").write_text(json.dumps({"model_id": plan.model_id,
                    "recipe_revision": plan.source_revision, "plan_id": plan.id, "plan_hash": plan.plan_hash,
                    "license": plan.license.model_dump(mode="json"),
                    "artifacts": [item.model_dump(mode="json") for item in plan.artifacts]}, indent=2) + "\n")
                job.phase, job.message = "installing", "Installing the complete verified directory"
                self.save_job(job)
                if target.exists():
                    raise ProvisioningConflict("Installation target appeared; existing files were preserved")
                stage.rename(target)
            if not installation_matches(recipe):
                raise ValueError("Installed files no longer match the approved artifacts")
            installed_hash = installation_hash(recipe)
            assert installed_hash is not None
            job.result = ProvisioningResult(installed=True, installation_path=str(target),
                artifact_hashes={item.filename: item.expected_sha256 for item in plan.artifacts},
                smoke_status="not_run", message="Pinned artifacts verified; inference has not yet passed")
            job.phase, job.progress, job.message = "validating", .85, "Running one bounded black-image inference; this is not an accuracy benchmark"
            self.save_job(job)
            observed = SmokeObservation.model_validate(self._smoke(plan.model_id, deadline)).model_dump(mode="json")
            self._assert_plan_current(plan, target_changed=True)
            if installed_hash != installation_hash(recipe):
                raise ProvisioningConflict("Installed artifacts changed during validation")
            receipt = ProvisioningHealth.model_validate({"id": uuid.uuid4().hex, "model_id": plan.model_id,
                "job_id": job.id, "plan_hash": plan.plan_hash, "created_at": now(),
                "installation_hash": installed_hash, "runtime_snapshot": plan.runtime_snapshot, **observed})
            atomic_model(self.path("health", receipt.id), receipt)
            atomic_model(health_path(plan.model_id), receipt)
            job.result.smoke_status, job.result.health_receipt_id = "passed", receipt.id
            job.result.message = "Installed and executed on a generated black image; no quality claim"
            job.status, job.phase, job.progress, job.message = "completed", "completed", 1, job.result.message
        except Exception as error:
            if job is None:
                raise
            job.status = "interrupted" if self.stopped.is_set() else "failed"
            job.phase = "interrupted" if self.stopped.is_set() else "failed"
            job.error = f"{type(error).__name__}: {error}"[:3000]
            job.message = "No verified callable result was produced; review the error before explicitly retrying"
            if job.result is not None and job.result.installed:
                job.result.smoke_status = "failed"
                job.result.message = "Pinned weights remain installed; execution validation did not pass"
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
            try:
                if job is not None:
                    self.save_job(job)
            finally:
                model_lease.release()
                lease.release()

    def health(self, identifier: str) -> ProvisioningHealth:
        return ProvisioningHealth.model_validate_json(self.path("health", identifier).read_text())

    def close(self) -> None:
        self.stopped.set()
        for thread in self.threads:
            thread.join(timeout=2)
