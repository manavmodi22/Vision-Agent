"""Immutable plans and append-only action evidence over existing execution gates."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, JsonValue

from agent.machine import TOOLS, AgentConflict, Phase
from agent.state_contracts import CapturedCall
from engine.eval import dataset_hash, spec_hash
from engine.eval.hashes import file_hash
from engine.media import media_fingerprint
from engine.platform.experiments import experiment_policy
from engine.service import WorkspaceService
from engine.store.models import now
from engine.store.repository import atomic_model
from spec.models import EvaluationResult, PipelineSpec
from spec.planning import CandidateModelSelection, PlanningOptions
from spec.platform import (
    Artifact,
    ArtifactContent,
    BuildPlan,
    EvaluationReport,
    ExecutionRun,
    PlanMetric,
    PlanSnapshot,
    PlatformReplay,
    ToolEvent,
)
from spec.skills import SkillReference


def encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(encoded(value)).hexdigest()


class PlatformStore:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def root(self, project_id: str) -> Path:
        return self.service.root(project_id) / "platform"

    def path(self, project_id: str, group: str, identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32,64}", identifier):
            raise ValueError("Invalid platform identifier")
        return self.root(project_id) / group / f"{identifier}.json"

    def immutable(self, path: Path, value: BaseModel) -> None:
        if path.exists():
            if json.loads(path.read_text()) != value.model_dump(mode="json"):
                raise AgentConflict("An immutable platform record cannot be overwritten")
            return
        atomic_model(path, value)

    def active_build(self, project_id: str) -> str | None:
        path = self.service.root(project_id) / "build.json"
        if path.exists():
            view = json.loads(path.read_text()).get("view", {})
            if view.get("status") == "running":
                value = view.get("id")
                return value if isinstance(value, str) else None
        return None

    def snapshot(self, project_id: str, candidates: list[PipelineSpec]) -> PlanSnapshot:
        from engine.eval.protocol import stable_configuration_hash
        from engine.eval.recipe import recipe_hash
        project, root = self.service.get_project(project_id), self.service.root(project_id)
        documents = {name: (root / name).read_text() if (root / name).exists() else None
                     for name in ("dataset-metadata.json", "active-holdout.json")}
        documents["evaluation_configuration"] = stable_configuration_hash(root, self.service.annotations(project_id))
        documents["evaluation_recipe"] = recipe_hash()
        zones = {path.name: path.read_text() for path in sorted((root / "zones").glob("*.json"))}
        model_hashes = [spec_hash(candidate, root) for candidate in candidates]
        if any(block.type in {"ocr", "barcode"} for candidate in candidates for block in candidate.blocks):
            bridge = Path(os.environ.get("VISION_APP_BINARY", ""))
            model_hashes.append(digest({"adapter": "apple-vision", "macos": platform.mac_ver()[0],
                "kernel": platform.release(), "bridge_sha256": file_hash(bridge) if bridge.is_file() else "missing"}))
        return PlanSnapshot(workspace_hash=digest({"media": media_fingerprint(project.media), "goal": project.brief,
            "candidates": [candidate.model_dump(mode="json", by_alias=True) for candidate in project.candidates],
            "documents": documents, "zones": zones}),
            dataset_hash=dataset_hash(self.service.annotations(project_id), root),
            model_hashes=model_hashes,
            settings_hash=digest(self.service.repository.settings().model_dump(mode="json")))

    def plans(self, project_id: str, build_id: str | None = None) -> list[BuildPlan]:
        plans = [self.plan(project_id, path.stem) for path in (self.root(project_id) / "plans").glob("*.json")]
        return sorted((plan for plan in plans if build_id is None or plan.build_id == build_id), key=lambda plan: plan.revision)

    def plan(self, project_id: str, plan_id: str) -> BuildPlan:
        raw = json.loads(self.path(project_id, "plans", plan_id).read_text())
        plan = BuildPlan.model_validate(raw)
        # Canonical graph aliases are part of the hash; absent additive metadata
        # must remain absent when verifying plans saved by the previous schema.
        canonical = plan.model_dump(mode="json", exclude={"content_hash"}, by_alias=True)
        canonical = {key: value for key, value in canonical.items() if key in raw}
        if plan.content_hash != digest(canonical):
            raise AgentConflict("The saved plan content hash is invalid")
        return plan

    def execution(self, project_id: str, operation_id: str) -> ExecutionRun | None:
        binding = self.path(project_id, "bindings", operation_id)
        return ExecutionRun.model_validate_json(binding.read_text()) if binding.exists() else None

    def save_run(self, run: ExecutionRun) -> None:
        run.updated_at = now()
        atomic_model(self.path(run.project_id, "executions", run.id), run)
        atomic_model(self.path(run.project_id, "bindings", run.operation_id), run)

    def publish(self, project_id: str, operation_id: str, goal: str, candidates: list[PipelineSpec],
                phase: Phase, reason: str, *, skills: list[SkillReference] | None = None,
                build_id: str | None = None, planning_options: PlanningOptions | None = None,
                model_selections: list[CandidateModelSelection] | None = None) -> tuple[BuildPlan, ExecutionRun]:
        with self.service.repository.lock:
            experiments, checkpoints = experiment_policy(candidates, phase)
            previous = self.execution(project_id, operation_id)
            if previous and previous.status in {"running", "planned", "paused"}:
                self.close(project_id, operation_id, "stale", "Superseded by a new plan revision; prior action outcomes remain in the timeline")
            build_id = build_id or self.active_build(project_id)
            if build_id:
                build = json.loads((self.service.root(project_id) / "build.json").read_text())
                if build.get("view", {}).get("id") != build_id:
                    raise AgentConflict("The plan's build was superseded")
                goal = str(build["prompt"])
            plans = self.plans(project_id)
            parent = plans[-1] if plans else None
            if (planning_options is None and parent and parent.build_id == build_id and parent.candidates == candidates
                    and parent.planning_options_artifact_id):
                planning_options = PlanningOptions.model_validate(self.artifact_content(project_id, parent.planning_options_artifact_id).content)
                model_selections = parent.model_selections
            source = self.snapshot(project_id, candidates)
            options_artifact = self.artifact(project_id, "planning_options", "Captured planning model options",
                planning_options.model_dump(mode="json")) if planning_options else None
            capabilities = {"block." + block.type for candidate in candidates for block in candidate.blocks}
            capabilities.update("model." + str(block.params.get("model", "owlv2-base-patch16")) for candidate in candidates
                                for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"})
            if any(block.type in {"ocr", "barcode"} for candidate in candidates for block in candidate.blocks):
                capabilities.add("model.apple-vision")
            if any(block.type == "vlm_judge" for candidate in candidates for block in candidate.blocks):
                capabilities.add("model.configured-vlm")
            if skills is None:
                from agent.skills import select_skills
                skills = [skill.reference for skill in select_skills(goal, self.service.get_project(project_id).use_case)]
            plan = BuildPlan(id=uuid.uuid4().hex, project_id=project_id,
                build_id=build_id, operation_id=operation_id,
                revision=parent.revision + 1 if parent else 1, parent_plan_id=parent.id if parent else None,
                created_at=now(), content_hash="", goal=goal, candidates=candidates, snapshot=source, skills=skills,
                assumptions=["Use the project's imported media and saved region geometry.",
                    "A sample preview does not establish accuracy.",
                    "Evaluation requires reviewed labels on the same held-out data for every candidate."],
                required_capabilities=sorted(capabilities),
                experiments=experiments,
                metrics=[PlanMetric(candidate_index=index, metric=candidate.eval.metric, target=candidate.eval.target,
                                    direction="minimize" if candidate.eval.metric == "count_mae" else "maximize")
                         for index, candidate in enumerate(candidates)],
                stop_conditions=["Stop on changed data, models, settings or workflow.",
                    "Stop if a required capability is unavailable or a tool fails.",
                    "Respect existing call, time and training budgets.", "Pause at human review and approval checkpoints."],
                human_checkpoints=checkpoints,
                revision_reason=reason, planning_options_artifact_id=options_artifact.id if options_artifact else None,
                model_selections=model_selections or [])
            plan = plan.model_copy(update={"content_hash": digest(plan.model_dump(mode="json", exclude={"content_hash"}, by_alias=True))})
            self.immutable(self.path(project_id, "plans", plan.id), plan)
            run = ExecutionRun(id=uuid.uuid4().hex, project_id=project_id, build_id=plan.build_id,
                operation_id=operation_id, plan_id=plan.id, plan_hash=plan.content_hash, phase=phase.value,
                created_at=now(), updated_at=now(), accepted_snapshot=source)
            self.save_run(run)
            return plan, run

    def authorize(self, project_id: str, operation_id: str, phase: Phase, name: str,
                  request: dict[str, JsonValue]) -> None:
        run = self.execution(project_id, operation_id)
        if run is None:
            raise AgentConflict("Save a typed build plan before executing vision actions")
        plan = self.plan(project_id, run.plan_id)
        if run.plan_hash != plan.content_hash or run.status in {"stale", "failed", "interrupted", "completed"}:
            raise AgentConflict("This saved plan revision is not executable; create a new revision")
        if self.snapshot(project_id, plan.candidates) != run.accepted_snapshot:
            self.close(project_id, operation_id, "stale", "Data, workflow, settings or model evidence changed")
            raise AgentConflict("The saved plan snapshot is stale; a new plan revision is required")
        planned = next((experiment.allowed_tools for experiment in plan.experiments if experiment.phase == phase.value), [])
        if name not in TOOLS[phase] or name not in planned:
            raise AgentConflict("This action is outside the saved plan's phase authority")
        if plan.planning_options_artifact_id:
            from engine.platform.planning_options import validate_current_options
            options = PlanningOptions.model_validate(self.artifact_content(project_id, plan.planning_options_artifact_id).content)
            validate_current_options(self.service, options, [selection.capability_id for selection in plan.model_selections])
        if name in {"pipeline_validate", "pipeline_run", "eval_run", "build_refine", "build_propose_labels", "build_train", "build_operate"}:
            from engine.capabilities import validate_experiment_capabilities
            validate_experiment_capabilities(self.service, plan.required_capabilities)
        if name in {"pipeline_validate", "pipeline_run", "eval_run", "build_operate"}:
            if "spec" in request:
                if PipelineSpec.model_validate(request["spec"]) not in plan.candidates:
                    raise AgentConflict("The requested candidate differs from the saved plan")
            else:
                index = request.get("candidate_index", 0)
                if not isinstance(index, int) or not 0 <= index < len(plan.candidates):
                    raise AgentConflict("The candidate is outside the saved plan")
                if self.service.candidate(project_id, index) != plan.candidates[index]:
                    raise AgentConflict("The saved candidate differs from the plan revision")
        run.status, run.phase = "running", phase.value
        self.save_run(run)

    def accept_effect(self, project_id: str, operation_id: str) -> None:
        run = self.execution(project_id, operation_id)
        if run:
            run.accepted_snapshot = self.snapshot(project_id, self.plan(project_id, run.plan_id).candidates)
            self.save_run(run)

    def close(self, project_id: str, operation_id: str, status: str, error: str | None = None) -> None:
        run = self.execution(project_id, operation_id)
        if run:
            run = ExecutionRun.model_validate({**run.model_dump(), "status": status, "error": error})
            self.save_run(run)

    def artifact(self, project_id: str, kind: str, title: str, content: dict[str, JsonValue]) -> Artifact:
        raw = encoded(content)
        identifier = hashlib.sha256(raw).hexdigest()
        path = self.path(project_id, "artifacts", identifier)
        if path.exists():
            return ArtifactContent.model_validate_json(path.read_text()).artifact
        artifact = Artifact.model_validate(dict(id=identifier, project_id=project_id, kind=kind, title=title,
                                               created_at=now(), sha256=identifier, size_bytes=len(raw)))
        self.immutable(path, ArtifactContent(artifact=artifact, content=content))
        return artifact

    def artifact_content(self, project_id: str, artifact_id: str) -> ArtifactContent:
        result = ArtifactContent.model_validate_json(self.path(project_id, "artifacts", artifact_id).read_text())
        if digest(result.content) != result.artifact.sha256:
            raise AgentConflict("Saved artifact content hash is invalid")
        return result

    def events(self, project_id: str, build_id: str | None = None) -> list[ToolEvent]:
        events = [ToolEvent.model_validate_json(path.read_text()) for path in (self.root(project_id) / "events").glob("*.json")]
        return sorted((event for event in events if build_id is None or event.build_id == build_id), key=lambda event: event.sequence)

    def record_call(self, project_id: str, operation_id: str, call: CapturedCall, phase: Phase) -> None:
        with self.service.repository.lock:
            stage = "started" if call.status == "running" else call.status
            event_id = digest([operation_id, call.id, stage])
            path = self.path(project_id, "events", event_id)
            if path.exists():
                return
            events = self.events(project_id)
            start = next((event for event in events if event.call_id == call.id and event.stage == "started"), None)
            run = self.execution(project_id, operation_id)
            input_artifact = self.artifact(project_id, "tool_input", f"{call.name} input", call.request)
            output_artifact = None
            if call.result is not None:
                kind = "model_response" if call.kind == "llm" else (
                    "planning_options" if call.name == "planning_options" else
                    "preview" if call.name in {"pipeline_run", "build_refine", "build_operate"} else
                    "evaluation" if call.name == "eval_run" else "tool_output")
                output_artifact = self.artifact(project_id, kind, f"{call.name} result", call.result)
            stamp_ns = call.started_ns if stage == "started" else call.ended_ns or call.started_ns
            event = ToolEvent.model_validate(dict(id=event_id, sequence=events[-1].sequence + 1 if events else 1,
                project_id=project_id, build_id=start.build_id if start else run.build_id if run else self.active_build(project_id),
                operation_id=operation_id, execution_id=start.execution_id if start else run.id if run else None,
                plan_id=start.plan_id if start else run.plan_id if run else None, call_id=call.id, kind=call.kind, stage=stage,
                name=call.name, phase=phase.value, at=datetime.fromtimestamp(stamp_ns / 1e9, UTC).isoformat(),
                duration_ms=(call.ended_ns - call.started_ns) / 1e6 if call.ended_ns else None,
                model_identity=f"Reported model alias: {call.name}" if call.kind == "llm" else None, input_artifact_id=input_artifact.id,
                output_artifact_id=output_artifact.id if output_artifact else None, error=call.error))
            self.immutable(path, event)
            if call.name == "eval_run" and call.status == "completed" and call.result and run and output_artifact:
                score = EvaluationResult.model_validate(call.result)
                candidate_index = call.request.get("candidate_index", 0)
                report = EvaluationReport(id=call.id, project_id=project_id, execution_id=run.id,
                    plan_id=run.plan_id, candidate_index=candidate_index if isinstance(candidate_index, int) else 0,
                    artifact_id=output_artifact.id, spec_hash=score.spec_hash, dataset_hash=score.dataset_hash,
                    metric=score.metric, target=score.target, passed=score.passed, sample_count=score.sample_count,
                    protocol_id=score.protocol_id, protocol_hash=score.protocol_hash,
                    evidence_scope=score.evidence_scope, promotion_eligible=score.promotion_eligible,
                    evidence_reasons=score.evidence_reasons,
                    metrics={"count_mae": score.count_mae, "precision": score.precision, "recall": score.recall,
                             "text_accuracy": score.text_accuracy, "character_error_rate": score.character_error_rate,
                             "word_error_rate": score.word_error_rate})
                self.immutable(self.path(project_id, "evaluations", report.id), report)

    def replay(self, project_id: str, execution_id: str) -> PlatformReplay:
        run = ExecutionRun.model_validate_json(self.path(project_id, "executions", execution_id).read_text())
        plan = self.plan(project_id, run.plan_id)
        events = [event for event in self.events(project_id) if event.execution_id == execution_id]
        references = {ref for event in events for ref in (event.input_artifact_id, event.output_artifact_id) if ref}
        if plan.planning_options_artifact_id:
            references.add(plan.planning_options_artifact_id)
        reports = [EvaluationReport.model_validate_json(path.read_text())
                   for path in (self.root(project_id) / "evaluations").glob("*.json")]
        return PlatformReplay(plan=plan, execution=run, events=events,
            artifacts=[self.artifact_content(project_id, ref).artifact for ref in sorted(references)],
            evaluations=[report for report in reports if report.execution_id == execution_id])
