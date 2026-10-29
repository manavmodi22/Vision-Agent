"""Expose actual registered MCP schemas, without invoking any tool."""
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from engine.capabilities.common import app_license, code_provenance, evidence, now, small_hash
from engine.service import WorkspaceService
from spec.capabilities import CapabilityHardware, CapabilityManifest, CapabilityReadiness

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
READ_ONLY = {"blocks_list", "block_schema", "frames_sample", "review_queue", "events_query", "dataset_context",
             "evidence_context", "evidence_execute", "agent_state_get", "build_context", "build_agent_state",
             "build_refinement_context"}


async def tool_catalog(service: WorkspaceService) -> list[CapabilityManifest]:
    from mcp_server.server import build_server

    tools = await build_server(service.repository.root, service=service).list_tools()
    source_dir = Path(__file__).parents[2] / "mcp_server"
    provenance = code_provenance(source_dir / "server.py")
    provenance.hashes = {path.name: digest for path in source_dir.glob("*.py") if (digest := small_hash(path))}
    result = []
    for tool in tools:
        name = tool.name
        effects = ["read_project"] if name in READ_ONLY else ["write_diagnostics"]
        if name.endswith("_tool_call"):
            effects = ["dispatch_phase_authorized_tool", "effects_of_selected_tool", "write_diagnostics"]
        if name in {"pipeline_run", "pipeline_validate"}:
            effects = ["read_project", "local_inference"]
        elif name in {"media_import", "eval_create", "eval_run", "suggest_labels", "build_refine", "build_prepare_review", "build_propose_labels"}:
            effects = ["read_project", "write_project"] + (["local_inference"] if name in {"suggest_labels", "build_refine", "build_propose_labels", "eval_run"} else [])
        elif name == "build_train":
            effects = ["read_project", "write_model_weights", "local_training", "requires_human_training_approval"]
        elif name == "build_operate":
            effects = ["read_project", "local_inference", "write_evidence", "queue_external_delivery", "requires_deployment_approval"]
        task = "evidence" if name.startswith("evidence") or name in {"events_query", "review_queue"} else "training" if name == "build_train" else "evaluation" if name.startswith("eval_") else "annotation" if "labels" in name or "review" in name else "media" if name in {"media_import", "frames_sample"} else "orchestration"
        result.append(CapabilityManifest(id="tool." + name, name=name, kind="tool",
            description=tool.description or "Registered local MCP tool", availability="installed", implemented=True,
            installation_ready=True, callable=True, task_types=[task], version="0.1", license=app_license(),
            provenance=provenance,
            hardware=CapabilityHardware(platforms=["host"], notes=["Selected pipeline/model prerequisites are validated at invocation."]),
            side_effects=effects, input_schema=JSON_OBJECT.validate_python(tool.inputSchema),
            output_schema=JSON_OBJECT.validate_python(tool.outputSchema or {}), install_method="bundled",
            readiness=CapabilityReadiness(state="ready", reason="Typed MCP tool is registered. Catalog visibility grants no phase or human approval.",
                checked_at=now(), evidence_scope="prerequisites", evidence=[evidence("adapter", name, True, "Input/output schema discovered from the actual FastMCP registry; the tool was not invoked.")])))
    return result
