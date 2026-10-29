"""Background control plane for one durable describe-to-app build per project."""

import asyncio
import json
import os
from time import time

from pydantic import JsonValue

from agent import build_orchestrator
from agent.graph_summary import describe_pipeline
from agent.machine import AgentConflict, AgentState, EvaluationEvidence, Phase
from agent.planner import plan as agent_plan
from agent.refinement import interpret_refinement, parse_refinement
from engine.agent_state import AgentStateStore
from engine.builds.store import BuildRecord, BuildStore
from engine.service import WorkspaceService
from engine.store.models import Deployment, Message
from engine.zones import read_zone_state
from spec.build import BuildContinueRequest, BuildStatus
from spec.models import EvaluationResult, RunResult
from spec.refinement import RefinementBatch, RefinementPatch


class BuildManager:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self.store = BuildStore(service)
        self.agent_states = AgentStateStore(service)
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def status(self, project_id: str) -> BuildStatus:
        return self.store.public(self.store.get(project_id))

    def settings(self, project_id: str) -> dict[str, JsonValue]:
        project = self.service.get_project(project_id)
        settings = self.service.repository.settings().model_dump(mode="json")
        settings.update({"project_id": project_id, "mcp_data_dir": str(self.service.repository.root),
                         "use_case": project.use_case, "clarification_count": project.clarification_count})
        if project.fixture:
            settings["detector_model"] = "fixture-color-v1"
        return settings

    def _spawn(self, record: BuildRecord) -> None:
        task = asyncio.create_task(self._run(record.view.project_id, record.view.id), name=f"build-{record.view.id[:8]}")
        self.tasks[record.view.project_id] = task

    async def start(self, project_id: str, prompt: str) -> BuildStatus:
        if not prompt.strip() or len(prompt) > 8000:
            raise ValueError("Describe your goal in 1–8,000 characters")
        record = await asyncio.to_thread(self.store.create, project_id, prompt.strip())
        if not self.service.get_project(project_id).media:
            record.view.phase = "awaiting_media"
            self.store.pause(record, "awaiting_review", "attach_media", "Add representative images or a short clip so I can build and test your app on real examples.")
        else:
            self._spawn(record)
        return self.store.public(record)

    async def continue_build(self, project_id: str, request: BuildContinueRequest) -> BuildStatus:
        with self.service.repository.lock:
            record = self.store.get(project_id)
            if record.view.status == "running":
                raise AgentConflict("This build is already running")
            followup = bool(request.prompt and record.view.status != "awaiting_clarification" and record.view.phase != "awaiting_zones")
            if followup:
                pass
            elif record.view.status == "completed":
                return self.store.public(record)
            elif record.view.phase == "awaiting_media":
                if not self.service.get_project(project_id).media:
                    return self.store.public(record)
                self.store.refresh_inputs(record)
                record.view.phase = "planning"
            elif record.view.phase == "awaiting_zones":
                zones = read_zone_state(self.service.root(project_id))
                if not zones.confirmed or not zones.zones:
                    return self.store.public(record)
                # Geometry is a human input checkpoint. Preserve the original goal
                # and replan it against the newly confirmed coordinates.
                self.store.refresh_inputs(record)
                record.view.questions, record.view.phase = [], "planning"
                self.store.log(record, "planning", "Using the saved regions to build and test your original goal.")
            elif record.view.status == "awaiting_clarification":
                if not request.prompt or not request.prompt.strip():
                    raise ValueError("Answer the agent's clarification before continuing")
                record.prompt += "\nUser clarification: " + request.prompt.strip()
                if len(record.prompt) > 10000:
                    raise ValueError("The goal and clarification exceed the build context budget")
                record.view.questions, record.view.phase = [], "planning"
                self.store.refresh_inputs(record)
            elif request.action == "improve":
                self.store.assert_current(record)
                if not request.training_approved:
                    raise ValueError("Improvement training requires an explicit human approval")
                if record.view.status != "awaiting_improvement" or record.view.selected_candidate_index is None:
                    raise ValueError("Evaluate the candidates before requesting training")
                if record.training_attempts >= 2:
                    raise ValueError("This build's two training attempts are exhausted; improve the examples or goal")
                reviewed = sum(row.reviewed for row in self.service.annotations(project_id).annotations)
                project = self.service.get_project(project_id)
                candidate = self.service.candidate(project_id, record.view.selected_candidate_index)
                if project.fixture or reviewed < 20 or len(project.candidates) >= 3 or sum(block.type in {"detect", "detect_open_vocab"} for block in candidate.blocks) != 1:
                    raise ValueError("Training needs a real detector pipeline, 20 reviewed images, and room for another candidate")
                record.operation.state.specialize(2)
                record.training_attempts += 1
                record.training_approved_hash = record.operation.input_fingerprint + record.data_hash
                record.view.phase = "training"
            elif record.view.status == "awaiting_approval" or (
                (record.view.status == "awaiting_improvement" or record.view.phase == "evidence")
                and (self.service.root(project_id) / "deployment.json").exists()
            ):
                self.store.assert_current(record)
                deployment_path = self.service.root(project_id) / "deployment.json"
                if not deployment_path.exists():
                    return self.store.public(record)
                deployment = Deployment.model_validate_json(deployment_path.read_text())
                if deployment.candidate_index != record.view.selected_candidate_index:
                    raise ValueError("The approved deployment does not match this build's selected candidate")
                reconciled = self.agent_states.reconcile(project_id, "build_approval")
                if reconciled.state.phase != Phase.OPERATE:
                    raise ValueError("Current human deployment approval is required")
                old_budget = record.operation.state.budget
                record.operation.state = reconciled.state
                record.operation.state.budget = old_budget
                record.view.phase = "operating"
            elif record.view.next_action == "configure_evaluation":
                self.store.refresh_inputs(record)
                record.operation.state.phase = Phase.EVALUATE
                record.view.phase = "reviewing"
            elif record.view.status in {"awaiting_review", "awaiting_improvement"}:
                self.store.assert_current(record, allow_labels=True)
                record.data_hash = self.store.labels_hash(project_id)
                record.view.phase = "reviewing"
            elif record.view.status in {"interrupted", "failed"}:
                if record.view.phase == "operating":
                    raise ValueError("The previous run's outcome is uncertain. Inspect recorded events; it will not be automatically repeated.")
                if record.view.phase == "training":
                    self.store.assert_current(record)
                    record.training_approved_hash = None
                    record.operation.state.phase = Phase.EVALUATE
                    self.store.log(record, "reviewing", "Training was interrupted. I will recheck the current reviewed candidates before offering another explicitly approved attempt.")
                self.store.assert_current(record, allow_labels=record.view.phase in {"labeling", "reviewing", "evaluating"})
                record.data_hash = self.store.labels_hash(project_id)
            else:
                raise ValueError("This build has no resumable action")
            if not followup:
                record.view.status, record.view.next_action = "running", "none"
                if record.view.phase == "planning":
                    record.operation.state.phase = Phase.PLAN
                    record.operation.state.evaluation = None
                    record.operation.state.deployment_approved = False
                    record.operation.state.override_reason = None
                    record.operation.state.approval_scope = None
                record.operation.owner_pid, record.operation.deadline = os.getpid(), time() + 900
                record.operation.state.budget.started_at = time()
                record.operation.status = "running"
                self.store.save(record)
        if followup:
            return await self.start(project_id, request.prompt or "")
        self._spawn(record)
        return self.store.public(record)

    def _planning_prompt(self, record: BuildRecord) -> str:
        project = self.service.get_project(record.view.project_id)
        summaries = [{"name": spec.name, "metric": spec.eval.metric, "target": spec.eval.target,
                      "blocks": [{"type": block.type, "params": block.params} for block in spec.blocks]}
                     for spec in project.candidates]
        context: dict[str, object] = {"existing_goal": project.brief[:1200], "existing_app": summaries,
                   "conversation": [{"role": item.role, "content": item.content[:500]} for item in project.messages[-4:]]}
        encoded = json.dumps(context, separators=(",", ":"))
        if len(encoded) + len(record.prompt) > 11800:
            context["conversation"], context["existing_goal"] = [], project.brief[:500]
            encoded = json.dumps(context, separators=(",", ":"))
        if len(encoded) + len(record.prompt) > 11800:
            raise ValueError("The current app and new goal exceed the planner context budget; shorten the follow-up")
        return "Current app context (preserve unless the user requests a change):\n" + encoded + "\nUser request:\n" + record.prompt

    async def _plan(self, project_id: str, build_id: str) -> None:
        record = self.store.get(project_id, build_id)
        self.store.assert_current(record)
        project = self.service.get_project(project_id)
        # Exact legacy commands remain deterministic. Clarification rounds always
        # use the local model with the original request and actual conversation.
        patch: RefinementPatch | RefinementBatch | None = (
            parse_refinement(record.prompt, project.candidates) if "User clarification:" not in record.prompt else None)
        if project.candidates and patch is None:
            decision = await interpret_refinement(record.prompt, self.settings(project_id), build_id,
                                                  record.view.selected_candidate_index or 0)
            if decision.questions:
                with self.service.repository.lock:
                    record = self.store.get(project_id, build_id)
                    self.store.assert_current(record)
                    project = self.service.get_project(project_id)
                    if len(decision.questions) > 3 - project.clarification_count:
                        raise ValueError("The three-question budget is exhausted; the existing app is preserved")
                    project.clarification_count += len(decision.questions)
                    project.messages += [Message(role="user", content=record.prompt),
                                         Message(role="assistant", content="\n".join(decision.questions))]
                    self.service.repository.save(project)
                    record.view.questions = decision.questions
                    self.store.pause(record, "awaiting_clarification", "answer_questions", "\n".join(decision.questions))
                return
            patch = RefinementBatch(patches=decision.patches)
        if patch is not None:
            result_patch = await build_orchestrator.refine_existing(self.settings(project_id), build_id, patch, record.view.selected_candidate_index or 0)
            with self.service.repository.lock:
                record = self.store.get(project_id, build_id)
                record.view.preview = result_patch.preview
                record.view.selected_candidate_index = result_patch.candidate_index
                record.operation.state.phase = Phase.EVALUATE
                record.operation.state.brief_confirmed = True
                record.operation.state.candidate_count = record.operation.state.compiled_count = len(project.candidates)
                project = self.service.get_project(project_id)
                project.messages += [Message(role="user", content=record.prompt), Message(role="assistant", content=result_patch.message)]
                project.brief += "\nRefinement: " + record.prompt
                self.service.repository.save(project)
                self.agent_states.reconcile(project_id, "build_refinement")
                self.store.log(record, "labeling", result_patch.message)
                self.store.save(record)
                if result_patch.requires_review:
                    record.view.phase = "reviewing"
                    self.store.pause(record, "awaiting_review", "review_labels", result_patch.message + " Review flags were reset for the expanded class set; existing boxes were preserved. Review the added classes before continuing.")
            return
        result = await agent_plan(self._planning_prompt(record), "media", self.settings(project_id))
        if not result.operation_id:
            raise ValueError("The planner did not return its durable operation token")
        with self.service.repository.lock:
            record = self.store.get(project_id, build_id)
            record.plan_operation_id = result.operation_id
            self.store.save(record)
        await asyncio.to_thread(self.agent_states.commit_plan, project_id, result.operation_id, result, record.prompt)
        with self.service.repository.lock:
            record = self.store.get(project_id, build_id)
            self.store.refresh_inputs(record)
            if result.questions:
                record.view.questions = result.questions
                if result.needs_zones:
                    record.view.phase = "awaiting_zones"
                    self.store.pause(record, "awaiting_review", "define_zones", result.message)
                else:
                    self.store.pause(record, "awaiting_clarification", "answer_questions", result.message)
                return
            operation = self.agent_states.operation(project_id, result.operation_id)
            previews = [call.result for call in operation.calls if call.name == "pipeline_run" and call.status == "completed" and call.result]
            if not previews:
                raise ValueError("The planner supplied no captured sample preview")
            record.view.preview = RunResult.model_validate(previews[0])
            record.view.selected_candidate_index = 0
            prior_budget = record.operation.state.budget
            record.operation.state = self.agent_states.get(project_id).state
            record.operation.state.budget = prior_budget
            detections = sum(len(frame.detections) for frame in record.view.preview.frames)
            self.store.log(record, "previewing", f"Compiled {len(result.candidates)} candidate(s) and previewed {len(record.view.preview.frames)} images; observed {detections} detections. {describe_pipeline(result.candidates[0])} Accuracy has not been evaluated.")
            models = sorted({str(block.params.get("model", "owlv2-base-patch16")) for candidate in result.candidates
                             for block in candidate.blocks if block.type in {"detect", "detect_open_vocab"}})
            if any(block.type in {"ocr", "barcode"} for candidate in result.candidates for block in candidate.blocks):
                models.append("Apple Vision")
            policy = "Candidate adapters: " + ", ".join(models) + ". Their quality still requires evaluation on reviewed examples."
            self.store.log(record, "labeling", policy)
            self.store.save(record)

    async def _labels(self, project_id: str, build_id: str) -> None:
        context, proposal = await build_orchestrator.prepare_labels(self.settings(project_id), build_id)
        with self.service.repository.lock:
            record = self.store.get(project_id, build_id)
            if len(set(context.comparison_scopes)) > 1:
                message = "These candidates cover different tasks, object classes, zones or event rules, so their scores cannot be compared. Refine them to one common goal before continuing; the current graphs are preserved."
                record.view.questions = [message]
                record.view.phase = "clarifying_scope"
                project = self.service.get_project(project_id)
                if project.clarification_count >= 3:
                    raise ValueError(message)
                project.clarification_count += 1
                project.messages.append(Message(role="assistant", content=message))
                self.service.repository.save(project)
                self.store.pause(record, "awaiting_clarification", "answer_questions", message)
                return
            if context.review_subset_created:
                self.store.log(record, "reviewing", "Selected the first ten imported images as a bounded evaluation subset; existing annotations and review flags were preserved. This does not establish scene independence.")
            if proposal is not None:
                suggested = sum(row.proposal is not None and not row.reviewed for row in proposal.annotations)
                self.store.log(record, "reviewing", f"{suggested} images have unverified detector suggestions. Existing manual labels and prior proposals were retained; reviewed labels were not overwritten.")
            if 10 <= context.evaluation_image_count <= 50 and context.evaluation_reviewed_count == context.evaluation_image_count:
                self.store.log(record, "evaluating", f"Testing all {context.candidate_count} candidate(s) on {context.evaluation_image_count} reviewed images.")
                self.store.save(record)
                return
            message = (f"Review the labels on {context.evaluation_image_count} evaluation images, then continue. "
                       f"{context.evaluation_reviewed_count} are reviewed. Evaluation requires 10–50 reviewed images; suggestions are not ground truth.")
            if not context.can_propose_labels and not context.fixture:
                message += " This workflow requires manually reviewed expected text or labels; automatic detector proposals do not apply."
            record.view.phase = "reviewing"
            self.store.pause(record, "awaiting_review", "review_labels", message)

    def _scored(self, project_id: str, build_id: str, results: list[EvaluationResult], selected: int, preview: RunResult) -> None:
        with self.service.repository.lock:
            record = self.store.get(project_id, build_id)
            record.view.evaluations, record.view.selected_candidate_index, record.view.preview = results, selected, preview
            best = results[selected]
            budget = record.operation.state.budget
            record.operation.state = AgentState(phase=Phase.EVALUATE, budget=budget, brief_confirmed=True,
                                                candidate_count=len(results), compiled_count=len(results))
            record.operation.state.record_evaluation(EvaluationEvidence(spec_hash=best.spec_hash, dataset_hash=best.dataset_hash,
                passed=best.passed, sample_count=best.sample_count, reviewed=True, protocol_id=best.protocol_id,
                protocol_hash=best.protocol_hash, promotion_eligible=best.promotion_eligible))
            self.store.refresh_inputs(record)
            value = getattr(best, best.metric)
            self.store.log(record, "evaluating", f"Evaluated all {len(results)} candidate(s). Candidate {selected + 1} achieved {best.metric} {value:.3f} against target {best.target:.3f} on {best.sample_count} reviewed images.")
            if best.passed and best.promotion_eligible:
                record.view.phase = "approval"
                self.store.pause(record, "awaiting_approval", "approve_deployment", "The selected candidate passed its declared target. Review its results and approve deployment to run and record evidence.")
            elif best.passed:
                record.view.phase = "evidence"
                reasons = " ".join(best.evidence_reasons)
                self.store.pause(record, "awaiting_review", "configure_evaluation",
                    "The numeric target passed on this validation sample. Configure independent acceptance for the selected candidate, or explicitly approve a bounded local-only trial. " + reasons)
            else:
                project = self.service.get_project(project_id)
                ready = (not project.fixture and sum(row.reviewed for row in self.service.annotations(project_id).annotations) >= 20
                         and len(project.candidates) < 3 and record.training_attempts < 2
                         and sum(block.type in {"detect", "detect_open_vocab"} for block in project.candidates[selected].blocks) == 1)
                record.view.phase = "improvement"
                message = "The target was missed. " + ("You can approve a two-minute local training attempt, followed by another comparison on reviewed held-out images."
                    if ready else "Correct or add representative reviewed examples, then continue. Training needs a real detector, 20 reviewed images, and an available candidate slot.")
                self.store.pause(record, "awaiting_improvement", "approve_training" if ready else "review_labels", message)

    def acceptance_scored(self, project_id: str, candidate_index: int, score: EvaluationResult) -> None:
        """Publish an actual human-started acceptance result without approving or running it."""
        with self.service.repository.lock:
            try:
                record = self.store.get(project_id)
            except FileNotFoundError:
                return
            if record.view.selected_candidate_index != candidate_index:
                return
            self.service.validate_evaluation(project_id, score)
            record.operation.state.phase = Phase.EVALUATE
            record.operation.state.record_evaluation(EvaluationEvidence(spec_hash=score.spec_hash,
                dataset_hash=score.dataset_hash, passed=score.passed, sample_count=score.sample_count, reviewed=True,
                protocol_id=score.protocol_id, protocol_hash=score.protocol_hash, promotion_eligible=score.promotion_eligible))
            self.store.refresh_inputs(record)
            self.store.log(record, "acceptance", f"Measured the selected candidate on {score.sample_count} reserved acceptance images: {score.metric} {getattr(score, score.metric):.3f}; target {score.target:.3f}.")
            if score.passed and score.promotion_eligible:
                record.view.phase = "approval"
                self.store.pause(record, "awaiting_approval", "approve_deployment",
                    "The selected candidate met the declared independent acceptance policy. Review its scope and explicitly approve before recording. Temporal event quality was not measured.")
            else:
                record.view.phase = "evidence"
                self.store.pause(record, "awaiting_review", "configure_evaluation",
                    "Acceptance did not qualify this candidate for promotion. " + " ".join(score.evidence_reasons)
                    + " A bounded local-only trial requires a separate explicit approval and reason.")

    async def _run(self, project_id: str, build_id: str) -> None:
        try:
            async with asyncio.timeout(900):
                record = self.store.get(project_id, build_id)
                if record.view.phase == "planning":
                    await self._plan(project_id, build_id)
                record = self.store.get(project_id, build_id)
                if record.view.status != "running":
                    return
                if record.view.phase in {"labeling", "previewing", "reviewing"}:
                    await self._labels(project_id, build_id)
                record = self.store.get(project_id, build_id)
                if record.view.status != "running":
                    return
                if record.view.phase == "evaluating":
                    self._scored(project_id, build_id, *await build_orchestrator.evaluate_all(self.settings(project_id), build_id))
                elif record.view.phase == "training":
                    self._scored(project_id, build_id, *await build_orchestrator.improve(self.settings(project_id), build_id, record.view.selected_candidate_index or 0))
                elif record.view.phase == "operating":
                    result = await build_orchestrator.run_approved(self.settings(project_id), build_id, record.view.selected_candidate_index or 0)
                    with self.service.repository.lock:
                        record = self.store.get(project_id, build_id)
                        record.view.preview = result
                        record.view.phase = "done"
                        record.operation.status = "completed"
                        self.store.pause(record, "completed", "none", f"Ran the approved app on {len(result.frames)} frames and recorded its evidence.")
                        self.store.traces.emit(record.operation)
        except asyncio.CancelledError:
            with self.service.repository.lock:
                record = self.store.get(project_id, build_id)
                self.store.pause(record, "interrupted", "retry", "The engine stopped. Continue to resume from the last safe step.")
            raise
        except Exception as error:
            cause: BaseException = error
            while isinstance(cause, BaseExceptionGroup) and cause.exceptions:
                cause = cause.exceptions[0]
            with self.service.repository.lock:
                record = self.store.get(project_id, build_id)
                record.operation.error, record.operation.status = str(cause), "failed"
                self.store.pause(record, "failed", "retry", str(cause) or type(cause).__name__)
                self.store.traces.emit(record.operation)

    async def close(self) -> None:
        active = [task for task in self.tasks.values() if not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
