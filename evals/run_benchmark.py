"""Run pattern regression or live local-model planning; never conflate the two."""

import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.planner import PlannerError, plan
from agent.templates import build_template
from engine.compiler import compile_pipeline
from engine.runtime.fixtures import generate_demo
from engine.service import WorkspaceService


class BriefCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    use_case: Literal["pallets", "damage", "labels"]
    brief: str
    metric: str
    required_blocks: list[str]


class CaseResult(BaseModel):
    id: str
    spec_valid: bool
    expected_pattern: bool
    tool_calls: int = 0
    elapsed_s: float = 0
    eval_metric_reached: bool | None = None
    error: str | None = None


class BenchmarkReport(BaseModel):
    mode: Literal["template-regression", "live-planner"]
    model: str | None = None
    provenance: str
    cases: list[CaseResult] = Field(default_factory=list)


def load_cases(path: Path | None = None) -> list[BriefCase]:
    source = path or Path(__file__).with_name("warehouse_briefs.json")
    return [BriefCase.model_validate(item) for item in json.loads(source.read_text())]


def template_benchmark(project_root: Path) -> BenchmarkReport:
    """Tests authored patterns; the brief is not interpreted by a language model."""
    generate_demo(project_root)
    report = BenchmarkReport(mode="template-regression", provenance=(
        "Authored templates selected by declared use_case. Synthetic fixtures. "
        "This measures compiler/pattern regression, not LLM planning, inference accuracy or warehouse performance."
    ))
    for case in load_cases():
        started = monotonic()
        try:
            candidate = build_template(case.use_case, "media", "fixture-color-v1")[0]
            compile_pipeline(candidate, project_root)
            types = {block.type for block in candidate.blocks}
            expected = set(case.required_blocks) <= types and candidate.eval.metric == case.metric
            report.cases.append(CaseResult(id=case.id, spec_valid=True, expected_pattern=expected,
                                           elapsed_s=monotonic() - started))
        except ValueError as error:
            report.cases.append(CaseResult(id=case.id, spec_valid=False, expected_pattern=False,
                                           elapsed_s=monotonic() - started, error=str(error)))
    return report


async def live_benchmark(data_dir: Path, model: str, url: str, limit: int = 24) -> BenchmarkReport:
    """Calls the local LLM; compilation is measured, CV accuracy is not inferred."""
    service = WorkspaceService(data_dir)
    report = BenchmarkReport(mode="live-planner", model=model, provenance=(
        "Actual local-model calls with typed outputs and MCP compilation. Synthetic fixture source. "
        "eval_metric_reached remains null: a separate human-labelled real-image accuracy evaluation is required."
    ))
    for case in load_cases()[:limit]:
        project = service.create_project(f"Benchmark {case.id}", case.use_case)
        service.demo(project.id)
        started = monotonic()
        try:
            result = await plan(case.brief, "media", {
                "model_url": url, "planner_model": model, "project_id": project.id,
                "mcp_data_dir": str(data_dir), "use_case": case.use_case,
                "detector_model": "fixture-color-v1",
            })
            valid = bool(result.candidates)
            expected = any(set(case.required_blocks) <= {block.type for block in candidate.blocks}
                           and candidate.eval.metric == case.metric for candidate in result.candidates)
            report.cases.append(CaseResult(id=case.id, spec_valid=valid, expected_pattern=expected,
                                           elapsed_s=monotonic() - started, tool_calls=result.tool_calls,
                                           error=None if valid else "Model requested clarification."))
        except (ValueError, PlannerError) as error:
            report.cases.append(CaseResult(id=case.id, spec_valid=False, expected_pattern=False,
                                           elapsed_s=monotonic() - started, error=str(error),
                                           tool_calls=error.tool_calls if isinstance(error, PlannerError) else 0))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["templates", "live"], default="templates")
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--url", default="http://localhost:1234/v1")
    parser.add_argument("--limit", type=int, default=24)
    arguments = parser.parse_args()
    if arguments.mode == "live" and not arguments.model:
        parser.error("--model is required for a live planner benchmark")
    if arguments.mode == "live" and not 1 <= arguments.limit <= 24:
        parser.error("--limit must be between 1 and 24")
    report = (template_benchmark(arguments.workdir) if arguments.mode == "templates" else
              asyncio.run(live_benchmark(arguments.workdir, arguments.model, arguments.url, arguments.limit)))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report.model_dump_json(indent=2) + "\n")
    print(report.model_dump_json(indent=2))
    if not all(case.spec_valid and case.expected_pattern for case in report.cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
