"""Actual local-model interpretation benchmark on isolated synthetic applications."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter

from agent.build_orchestrator import refine_existing
from agent.refinement import interpret_refinement
from agent.refinement_contracts import RefinementDecision
from agent.templates import build_template
from engine.builds.refinement_edits import apply_edit, detector_classes
from engine.builds.store import BuildStore
from engine.service import WorkspaceService
from engine.store.models import Message
from spec.models import PipelineSpec
from spec.refinement import RefinementBatch, RefinementPatch


class Case(BaseModel):
    id: str
    context: Literal["pallets", "two_classes", "count_only", "labels", "read_only"] = "pallets"
    prompt: str
    expected: list[dict[str, JsonValue]] = Field(default_factory=list)
    questions: bool = False
    answer: str | None = None
    expected_after: list[dict[str, JsonValue]] = Field(default_factory=list)


def expected_graph(candidates: list[PipelineSpec], patches: list[RefinementPatch]) -> list[PipelineSpec]:
    copies = [candidate.model_copy(deep=True) for candidate in candidates]
    names = {name.casefold(): name for candidate in copies for name in detector_classes(candidate)}
    for patch in patches:
        for index in range(len(copies)) if patch.target_scope() == "all" else [0]:
            apply_edit(copies[index], patch, names)
    return copies


def matches(decision: RefinementDecision, expected: list[dict[str, JsonValue]], questions: bool,
            candidates: list[PipelineSpec]) -> bool:
    if questions:
        return 1 <= len(decision.questions) <= 3 and not decision.patches
    if decision.questions:
        return False
    # Score the exact intended graph, including all unchanged fields. Equivalent
    # remove/replace edits and an omitted already-correct operator are valid.
    wanted = [RefinementPatch.model_validate(value) for value in expected]
    return expected_graph(candidates, decision.patches) == expected_graph(candidates, wanted)


async def run(args: argparse.Namespace) -> None:
    cases = TypeAdapter(list[Case]).validate_json(Path(args.cases).read_text())
    if args.ids:
        cases = [case for case in cases if case.id in args.ids.split(",")]
    args.workspace.mkdir(parents=True, exist_ok=True)
    service, records = WorkspaceService(args.workspace), []
    for case in cases:
        project = service.create_project("Live refinement: " + case.id, "custom")
        service.demo(project.id)
        reading = case.context in {"labels", "read_only"}
        specs = build_template("labels" if reading else "pallets", "media", "fixture-color-v1")[:1]
        if case.context in {"count_only", "read_only"}:
            specs[0].blocks = [block for block in specs[0].blocks if block.type not in {"rule", "match", "sink_event"}]
        if case.context == "two_classes":
            next(block for block in specs[0].blocks if block.type == "detect").params["classes"] = ["pallet", "carton"]
        second = specs[0].model_copy(deep=True)
        second.name += " alternative"
        specs.append(second)
        service.save_candidates(project.id, specs, "Read product labels" if reading else "Count pallets by lane")
        store = BuildStore(service)
        record = store.create(project.id, case.prompt)
        settings: dict[str, JsonValue] = {"project_id": project.id, "mcp_data_dir": str(args.workspace),
            "model_url": args.url, "planner_model": args.model}
        row: dict[str, JsonValue] = {"id": case.id, "prompt": case.prompt, "context": case.context,
            "project_id": project.id, "build_id": record.view.id, "provenance": "original generated synthetic fixture pixels", "passed": False}
        started = monotonic()
        try:
            decision = await interpret_refinement(case.prompt, settings, record.view.id)
            row["decision"] = decision.model_dump(mode="json")
            passed = matches(decision, case.expected, case.questions, specs)
            if case.answer and decision.questions:
                current = service.get_project(project.id)
                current.messages += [Message(role="user", content=case.prompt), Message(role="assistant", content="\n".join(decision.questions))]
                current.clarification_count += len(decision.questions)
                service.repository.save(current)
                followup = case.prompt + "\nUser clarification: " + case.answer
                decision = await interpret_refinement(followup, settings, record.view.id)
                row["followup_decision"] = decision.model_dump(mode="json")
                passed = passed and matches(decision, case.expected_after, False, specs)
            if decision.patches and passed:
                # Native OCR must be explicitly present. Detector previews always
                # execute actual generated pixels; no real-world accuracy claim.
                if not reading or os.environ.get("VISION_APP_BINARY"):
                    result = await refine_existing(settings, record.view.id, RefinementBatch(patches=decision.patches), 0)
                    exact = service.get_project(project.id).candidates == expected_graph(specs, decision.patches)
                    row["exact_expected_graph"] = exact
                    passed = passed and exact
                    row["preview"] = TypeAdapter(JsonValue).validate_python({"frames": len(result.preview.frames),
                        "affected_candidates": result.affected_candidate_indices,
                        "previewed_candidates": result.previewed_candidate_indices,
                        "before_hashes": result.base_spec_hashes, "after_hashes": result.spec_hashes,
                        "requires_review": result.requires_review})
                else:
                    row["preview_skipped"] = "Native OCR executable was not provided; interpretation only"
            row["passed"] = passed
        except Exception as error:
            cause: BaseException = error
            while isinstance(cause, BaseExceptionGroup) and cause.exceptions:
                cause = cause.exceptions[0]
            row["error"] = str(cause)
        saved = store.get(project.id)
        row["model_calls"] = sum(call.kind == "llm" for call in saved.operation.calls)
        row["tool_calls"] = [{"name": call.name, "status": call.status} for call in saved.operation.calls if call.kind == "tool"]
        row["trace_id"] = saved.operation.trace_id
        row["elapsed_s"] = monotonic() - started
        row["no_approval_or_run"] = service.get_project(project.id).deployment_id is None and not service.events(project.id)
        records.append(row)
        report = {"model": args.model, "model_url": args.url, "scope": "Actual LLM language interpretation and typed patch/fixture preview; no warehouse accuracy claim",
            "passed": sum(row["passed"] is True for row in records), "total": len(records),
            "planned_cases": len(cases), "complete": len(records) == len(cases), "cases": records}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(f"{case.id}: {'PASS' if row['passed'] else 'FAIL'} ({row['elapsed_s']:.1f}s) {row.get('error', '')}", flush=True)
        saved.view.status = "completed"
        saved.operation.status = "completed"
        store.save(saved)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="evals/refinement_cases.json")
    parser.add_argument("--workspace", type=Path, default=Path(".visionapp-refinement-live").resolve())
    parser.add_argument("--output", type=Path, default=Path("artifacts/refinement-live.json"))
    parser.add_argument("--url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--model", default="visionapp-planner")
    parser.add_argument("--ids", default="")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
