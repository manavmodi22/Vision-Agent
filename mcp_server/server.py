"""Typed tools: validation and orchestration only; business logic stays in engine."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from mcp_server.contracts import (
    BlockSchemaResult,
    CatalogResult,
    DatasetContext,
    FramesResult,
    ProjectResult,
    RecordsResult,
    ValidationResult,
)
from spec.evidence import EvidenceAnswer, EvidenceContext, EvidenceQuery
from spec.models import EvalDataset, EvaluationResult, PipelineSpec, RunResult
from spec.planning import PlanningOptions

if TYPE_CHECKING:
    from engine.service import WorkspaceService


def build_server(data_dir: Path, *, service: WorkspaceService | None = None) -> FastMCP[None]:
    from engine.agent_state import AgentStateStore
    from engine.blocks import list_blocks
    from engine.blocks.registry import block_schema as schema_for_block
    from engine.builds.store import BuildStore
    from engine.compiler import compile_pipeline
    from engine.evidence_audit import EvidenceAuditStore
    from engine.service import WorkspaceService
    from mcp_server.builds import register_build_tools
    from mcp_server.durable import register_durable_tools
    from mcp_server.evidence_audit import register_evidence_audit

    service = service or WorkspaceService(data_dir)
    server: FastMCP[None] = FastMCP(
        "VisionApp", instructions="Local typed vision tools. Human deployment approval is not a tool.",
        log_level="WARNING",
    )

    def authorize_source(project_id: str, spec: PipelineSpec) -> None:
        root = service.root(project_id)
        source = spec.inputs["source"]
        path = (root / source.path).resolve()
        media_dir = (root / "media").resolve()
        imported = {Path(item).resolve() for item in service.get_project(project_id).media}
        if source.type == "image_folder" and path == media_dir:
            return
        if source.type == "image_file" and path in imported:
            return
        raise ValueError("Agent pipelines may only read the project's imported media.")

    @server.tool()
    def blocks_list() -> CatalogResult:
        """Discover implemented pipeline blocks, ports and parameter schemas."""
        return CatalogResult(blocks=list_blocks())

    @server.tool()
    def planning_options(project_id: str, detection_constraint: str | None = None, operation_id: str | None = None) -> PlanningOptions:
        """Discover installed adapter/task/vocabulary options without running inference."""
        from engine.platform.planning_options import planning_options as discover
        if operation_id:
            return AgentStateStore(service).planning_options(project_id, operation_id, detection_constraint)
        return discover(service, project_id, detection_constraint)

    @server.tool()
    def block_schema(block_type: str) -> BlockSchemaResult:
        """Return one block's documented input/output contract."""
        return BlockSchemaResult(block=schema_for_block(block_type))

    @server.tool()
    def pipeline_validate(project_id: str, spec: PipelineSpec) -> ValidationResult:
        """Compile a candidate against local models and the project's files."""
        try:
            authorize_source(project_id, spec)
            compile_pipeline(spec, service.root(project_id))
        except ValueError as error:
            return ValidationResult(valid=False, errors=[str(error)])
        return ValidationResult(valid=True)

    @server.tool()
    def pipeline_run(project_id: str, candidate_index: int = 0, spec: PipelineSpec | None = None) -> RunResult:
        """Preview a proposed or saved candidate on five sample frames; never deploy it."""
        if spec is not None:
            from engine.runtime import run_pipeline

            authorize_source(project_id, spec)
            return run_pipeline(spec, service.root(project_id), max_frames=5)
        return service.preview(project_id, candidate_index)

    @server.tool()
    def media_import(project_id: str, paths: list[str]) -> ProjectResult:
        """Import user-selected images or clips into a project."""
        return ProjectResult(project=service.import_media(project_id, paths).model_dump(mode="json", by_alias=True))

    @server.tool()
    def frames_sample(project_id: str, limit: int = 5) -> FramesResult:
        """List up to 50 previously imported image paths; does not read pixels."""
        if not 1 <= limit <= 50:
            raise ValueError("Frame limit must be between 1 and 50.")
        return FramesResult(paths=service.get_project(project_id).media[:limit])

    @server.tool()
    def eval_create(project_id: str, dataset: EvalDataset) -> EvalDataset:
        """Propose unreviewed annotations; only a human-facing UI may confirm labels."""
        if any(annotation.reviewed for annotation in dataset.annotations):
            raise ValueError("Agents cannot mark labels reviewed. Request a human review in the app.")
        return service.save_annotations(project_id, dataset)

    @server.tool()
    def eval_run(project_id: str, candidate_index: int = 0) -> EvaluationResult:
        """Evaluate a saved candidate against reviewed project annotations."""
        return service.evaluate(project_id, candidate_index)

    @server.tool()
    def review_queue(project_id: str) -> RecordsResult:
        """Read hard frames collected by approved pipeline runs."""
        return RecordsResult(records=[record.model_dump(mode="json") for record in service.review(project_id)])

    @server.tool()
    def events_query(project_id: str) -> RecordsResult:
        """Read persisted local evidence events for this project."""
        return RecordsResult(records=[record.model_dump(mode="json") for record in service.events(project_id)])

    @server.tool()
    def evidence_context(project_id: str, timezone: str | None = None) -> EvidenceContext:
        """Read complete evidence vocabulary and host/request timezone without changing project state."""
        from engine.evidence_query import evidence_context as load_context

        return load_context(service, project_id, timezone)

    @server.tool()
    def evidence_execute(project_id: str, query: EvidenceQuery, timezone: str, reference_time: datetime) -> EvidenceAnswer:
        """Execute fixed parameterized filters over all matching records; never count unique physical objects."""
        from engine.evidence_query import execute_evidence_query

        return execute_evidence_query(service, project_id, query, timezone, reference_time)

    @server.tool()
    def dataset_context(project_id: str) -> DatasetContext:
        """Read the user's class ontology, annotation progress and split counts."""
        from engine.datasets import DatasetService
        from engine.zones import read_zone_state

        manifest = DatasetService(service).manifest(project_id)
        zones = read_zone_state(service.root(project_id))
        splits: dict[str, int] = {}
        for item in manifest.images:
            splits[item.split] = splits.get(item.split, 0) + 1
        return DatasetContext(revision=manifest.revision, classes=[item.name for item in manifest.classes],
                              image_count=len(manifest.images), reviewed_count=sum(item.reviewed for item in manifest.images),
                              annotation_count=sum(item.annotation_count for item in manifest.images), split_counts=splits,
                              saved_zone_ids=[zone.id for zone in zones.zones] if zones.confirmed else [],
                              zones_confirmed=zones.confirmed, zone_origin=zones.origin)

    @server.tool()
    def suggest_labels(project_id: str, candidate_index: int = 0, max_frames: int = 5) -> EvalDataset:
        """Return unreviewed detector suggestions; never save, overwrite or approve user labels."""
        from engine.runtime.autolabel import propose_labels

        return propose_labels(service.candidate(project_id, candidate_index), service.annotations(project_id),
                              service.root(project_id), max_frames=max_frames)

    register_durable_tools(server, AgentStateStore(service))
    register_evidence_audit(server, EvidenceAuditStore(service))
    register_build_tools(server, BuildStore(service))
    return server
