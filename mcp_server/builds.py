"""Actual build tools with human-only training grants and durable tool capture."""

import asyncio
import hashlib
import json

from mcp.server.fastmcp import FastMCP
from pydantic import JsonValue, TypeAdapter

from agent.machine import AgentState
from agent.refinement_capabilities import delivery_question
from agent.refinement_contracts import RefinementDecision
from agent.state_contracts import CapturedCall, ToolDispatchResult
from engine.builds.store import BuildStore
from engine.jobs import Job
from spec.build import BuildContext
from spec.evaluation import EvaluationProtocol
from spec.models import EvalDataset, RunResult
from spec.refinement import RefinementBatch, RefinementContext, RefinementPatch, RefinementResult
from spec.skills import SkillReference

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def register_build_tools(server: FastMCP[None], store: BuildStore) -> None:
    service = store.service

    @server.tool()
    def build_record_skills(project_id: str, build_id: str, skills: list[SkillReference]) -> AgentState:
        """Bind refinement interpretation to exact installed guidance hashes."""
        return store.record_skills(project_id, build_id, skills)

    @server.tool()
    def build_refine(project_id: str, build_id: str, patch: RefinementPatch | None = None,
                     candidate_index: int = 0, batch: RefinementBatch | None = None) -> RefinementResult:
        """Preview and commit only a typed bounded edit to the actual existing graph."""
        from engine.builds.refinement import refine_app

        record = store.get(project_id, build_id)
        if record.view.status != "running" or record.view.phase != "planning":
            raise ValueError("Graph refinement requires an active user-started build")
        store.assert_current(record)
        project = service.get_project(project_id)
        if question := delivery_question(record.prompt, project.messages[-1].content if project.messages else ""):
            raise ValueError(question)
        if (patch is None) == (batch is None):
            raise ValueError("Supply exactly one patch or atomic batch")
        if batch is not None:
            expected = batch.model_dump(mode="json")["patches"]
            if not record.refinement_decisions or record.refinement_decisions[-1].get("patches") != expected:
                raise ValueError("The batch must match this build's captured local-planner decision")
            return refine_app(service, project_id, batch, candidate_index)
        assert patch is not None
        return refine_app(service, project_id, patch, candidate_index)

    @server.tool()
    def build_refinement_context(project_id: str, candidate_index: int = 0) -> RefinementContext:
        """Read actual graph and conversation without mutating ontology or labels."""
        from engine.datasets import DatasetMetadata
        from engine.zones import read_zone_state

        project = service.get_project(project_id)
        if not 0 <= candidate_index < len(project.candidates):
            raise ValueError("Choose an existing app candidate")
        root = service.root(project_id)
        metadata_path = root / "dataset-metadata.json"
        metadata = DatasetMetadata.model_validate_json(metadata_path.read_text()) if metadata_path.exists() else DatasetMetadata()
        classes = {item.name for item in metadata.classes}
        classes.update(box.label for row in service.annotations(project_id).annotations for box in row.detections)
        for candidate in project.candidates:
            for block in candidate.blocks:
                labels = block.params.get("classes")
                if block.type in {"detect", "detect_open_vocab"} and isinstance(labels, list):
                    classes.update(label for label in labels if isinstance(label, str))
        zones = read_zone_state(root)
        return RefinementContext(candidates=project.candidates, selected_candidate_index=candidate_index,
            current_goal=project.brief, conversation=[{"role": item.role, "content": item.content} for item in project.messages],
            classes=sorted(classes), saved_zone_ids=[zone.id for zone in zones.zones] if zones.confirmed else [],
            clarification_count=project.clarification_count)

    @server.tool()
    def build_capture_start(project_id: str, build_id: str, name: str, request: dict[str, JsonValue]) -> CapturedCall:
        """Capture one actual local-model attempt and consume its persisted budget."""
        return store.start_model_call(project_id, build_id, name, request)

    @server.tool()
    def build_capture_finish(project_id: str, build_id: str, call_id: str,
                             result: dict[str, JsonValue] | None = None, error: str | None = None) -> AgentState:
        record = store.get(project_id, build_id)
        if not any(call.id == call_id and call.kind == "llm" for call in record.operation.calls):
            raise ValueError("Only a captured model call can be completed here")
        return store.finish_call(project_id, build_id, call_id, result, error).operation.state

    @server.tool()
    def build_record_refinement(project_id: str, build_id: str, decision: RefinementDecision) -> AgentState:
        """Persist a typed decision; this grants no graph mutation or human approval."""
        return store.record_refinement_decision(project_id, build_id, decision.model_dump(mode="json"))

    @server.tool()
    def build_agent_state(project_id: str, build_id: str) -> AgentState:
        """Bind to an existing human-started build; this cannot start or approve one."""
        record = store.get(project_id, build_id)
        if record.view.status != "running":
            raise ValueError("The build is not active")
        return record.operation.state

    @server.tool()
    def build_freeze_evaluation(project_id: str) -> EvaluationProtocol:
        """Freeze one validation protocol for all current alternatives; cannot consume acceptance."""
        return service.freeze_evaluation(project_id)

    @server.tool()
    def build_context(project_id: str) -> BuildContext:
        """Read sample/review readiness and candidate capabilities."""
        from engine.compiler import compile_pipeline
        from engine.eval.scope import detection_scope

        project = service.get_project(project_id)
        dataset, evaluation = service.annotations(project_id), service.evaluation_annotations(project_id)
        detector_count = sum(block.type in {"detect", "detect_open_vocab"} for block in project.candidates[0].blocks) if project.candidates else 0
        reviewed = sum(row.reviewed for row in dataset.annotations)
        scopes = []
        for candidate in project.candidates:
            scope = detection_scope(compile_pipeline(candidate, service.root(project_id)))
            payload = {"classes": sorted(scope.classes),
                       "tasks": sorted({"detection" if block.type in {"detect", "detect_open_vocab"} else block.type for block in candidate.blocks
                                        if block.type in {"detect", "detect_open_vocab", "ocr", "barcode", "vlm_judge"}}),
                       "zones": [[zone.model_dump(mode="json") for zone in stage] for stage in scope.zone_stages],
                       "behaviors": sorted(json.dumps({"type": block.type, "params": block.params}, sort_keys=True)
                                            for block in candidate.blocks if block.type in {"rule", "match"})}
            scopes.append(hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest())
        return BuildContext(image_count=len(dataset.annotations), reviewed_count=reviewed,
            evaluation_image_count=len(evaluation.annotations), evaluation_reviewed_count=sum(row.reviewed for row in evaluation.annotations),
            candidate_count=len(project.candidates), can_propose_labels=not project.fixture and detector_count == 1,
            fixture=project.fixture, training_eligible=not project.fixture and detector_count == 1 and reviewed >= 20 and len(project.candidates) < 3,
            comparison_scopes=scopes)

    @server.tool()
    def build_prepare_review(project_id: str) -> BuildContext:
        """Choose ten initial evaluation images for a large dataset; never mark them reviewed."""
        from engine.store.repository import atomic_model

        created = False
        with service.repository.lock:
            dataset = service.evaluation_annotations(project_id)
            holdout_path = service.root(project_id) / "active-holdout.json"
            if len(dataset.annotations) > 50 and not holdout_path.exists():
                atomic_model(holdout_path, EvalDataset(id=dataset.id + "-agent-evaluation", annotations=dataset.annotations[:10]))
                project = service.get_project(project_id)
                service.invalidate(project)
                service.repository.save(project)
                created = True
        return BuildContext.model_validate(build_context(project_id)).model_copy(update={"review_subset_created": created})

    @server.tool()
    def build_propose_labels(project_id: str, candidate_index: int = 0, max_frames: int = 50) -> EvalDataset:
        """Save only detector suggestions, preserving manual boxes and all human review flags."""
        from mcp_server.evaluation import visible_dataset
        return visible_dataset(service, project_id, service.propose_labels(project_id, candidate_index, max_frames))

    @server.tool()
    async def build_train(project_id: str, build_id: str, candidate_index: int) -> Job:
        """Consume a human API training grant, then await one bounded local job."""
        from engine.jobs import JobManager

        store.consume_training_approval(project_id, build_id, candidate_index)
        jobs = JobManager(service)
        job = await asyncio.to_thread(jobs.start, project_id, candidate_index, 2, 10, True)
        with service.repository.lock:
            record = store.get(project_id, build_id)
            record.training_job_id = job.id
            store.save(record)
        while job.status in {"queued", "running"}:
            await asyncio.sleep(2)
            job = await asyncio.to_thread(jobs.get, project_id, job.id)
        if job.status != "completed":
            raise ValueError(job.error or job.message)
        return job

    @server.tool()
    def build_operate(project_id: str, candidate_index: int) -> RunResult:
        """Run and record at most 50 frames only with current human deployment approval."""
        return service.run(project_id, candidate_index, max_frames=50)

    @server.tool()
    async def build_tool_call(project_id: str, build_id: str, name: str, arguments: dict[str, JsonValue]) -> ToolDispatchResult:
        """Dispatch a phase-allowed vision action and capture the actual engine result."""
        call = store.start_call(project_id, build_id, name, arguments)
        try:
            raw: object = await server.call_tool(name, arguments)
            if isinstance(raw, tuple) and len(raw) == 2:
                raw = raw[1]
            output = JSON_OBJECT.validate_python(raw)
        except Exception as error:
            store.finish_call(project_id, build_id, call.id, None, str(error))
            raise
        record = store.finish_call(project_id, build_id, call.id, output)
        return ToolDispatchResult(output=output, state=record.operation.state)
