"""Manual execution of one exact saved proposal; no fabricated agent authority."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from agent.graph_authoring import compose_graph, graph_model_selections  # noqa: E402
from engine.compiler import compile_pipeline  # noqa: E402
from engine.platform.planning_options import planning_options  # noqa: E402
from engine.runtime import run_pipeline  # noqa: E402
from engine.runtime_identity import source_identity  # noqa: E402
from engine.service import WorkspaceService  # noqa: E402
from spec.investigation import WorkflowDecision  # noqa: E402
from spec.model_bindings import validate_block_bindings  # noqa: E402

ARTIFACT_BASE = Path(__file__).resolve().parent
OUT = ARTIFACT_BASE / "actual-preview"
PROPOSAL = ARTIFACT_BASE.parent / "candidate.json"
NATIVE = ROOT / "dist/VisionApp.app/Contents/MacOS/VisionApp"
OLD_RUN = ROOT / ".visionapp/a0-investigation/run-20261029T180941Z"
OLD_PROJECT = OLD_RUN / "workspace/projects/1a32862295864799"
LEDGER = OLD_PROJECT / "investigations/70e4ba01eae04c7899f3e7988af27258/task.json"
FIXTURE = OLD_RUN / "item-and-shipping.png"
WORKSPACE = ROOT / ".visionapp/a0-investigation/manual-graph-preview-qwen35-call7-20261029/attempt2/workspace"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def save(name: str, value: object) -> None:
    path = OUT / name
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def effects(service: WorkspaceService, project_id: str) -> dict[str, object]:
    project = service.get_project(project_id)
    root = service.root(project_id)
    return {"candidate_count": len(project.candidates), "evaluation_count": len(project.evaluations),
            "approval_scope": project.approval_scope, "deployment_id": project.deployment_id,
            "persisted_event_count": len(service.events(project_id)), "review_count": len(service.review(project_id)),
            "deployment_file": (root / "deployment.json").exists(),
            "investigation_directory": (root / "investigations").exists(),
            "project_json_sha256": sha(root / "project.json"), "annotations_sha256": sha(root / "annotations.json")}


def main() -> None:
    if WORKSPACE.exists() or (OUT / "receipt.json").exists():
        raise ValueError("This one-shot diagnostic requires a fresh workspace and receipt")
    if not NATIVE.is_file():
        raise ValueError("The same native bridge used by the source run is unavailable")
    os.environ["VISION_APP_BINARY"] = str(NATIVE)
    OUT.mkdir(exist_ok=False)
    started = monotonic()
    protected = {str(p): sha(p) for p in (PROPOSAL, LEDGER, FIXTURE, OLD_RUN / "report.json", NATIVE)}
    original_project = snapshot(OLD_PROJECT)
    source_before = source_identity(ROOT)
    raw = PROPOSAL.read_bytes()
    proposal = json.loads(raw)
    decision = WorkflowDecision.model_validate(proposal["decision"])
    assert decision.action.graph.model_dump(mode="json") == proposal["decision"]["action"]["graph"]
    # Only this already inspected saved proposal is authorized for this diagnostic.
    assert [node.type for node in decision.action.graph.nodes] == ["frame_sample", "ocr"]
    assert decision.action.graph.nodes[1].model_capability_id == "model.apple-vision"
    (OUT / "proposal.json").write_bytes(raw)
    save("graph.json", proposal["decision"]["action"]["graph"])
    service = WorkspaceService(WORKSPACE)
    project = service.create_project("Manual exact-proposal diagnostic on generated fixture", "custom")
    project = service.import_media(project.id, [str(FIXTURE)])
    project.fixture = True
    project.synthetic = True
    project.data_origin = "Copied generated software fixture for manual diagnostic preview; no real-scene quality claim"
    service.repository.save(project)
    project_root = service.root(project.id)
    copied = Path(project.media[0])
    assert sha(copied) == sha(FIXTURE)
    options = planning_options(service, project.id)
    bindings = graph_model_selections([decision.action.graph], options)
    spec = compose_graph(decision.action.graph, "media", options)
    validate_block_bindings(spec, bindings, 0, options)
    compiled = compile_pipeline(spec, project_root)
    save("planning-options.json", options.model_dump(mode="json"))
    save("model-bindings.json", [item.model_dump(mode="json") for item in bindings])
    save("compiled-spec.json", spec.model_dump(mode="json", by_alias=True))
    save("compiled-plan.json", {"blocks": [b.model_dump(mode="json", by_alias=True) for b in compiled.blocks],
         "params": {key: value.model_dump(mode="json") for key, value in compiled.params.items()},
         "warnings": compiled.warnings,
         "inference_identities": {key: value.model_dump(mode="json") for key, value in compiled.inference_identities.items()}})
    before = effects(service, project.id)
    result = run_pipeline(spec, project_root, max_frames=1)
    save("run-result.json", result.model_dump(mode="json"))
    after = effects(service, project.id)
    assert len(result.frames) == 1 and len(result.frames[0].inferences) == 1
    assert result.frames[0].source_image_sha256 == sha(FIXTURE)
    assert result.frames[0].inferences[0].block_id == "reader"
    assert before == after
    assert not result.frames[0].events
    assert all(not row.reviewed for row in service.annotations(project.id).annotations)
    assert protected == {p: sha(Path(p)) for p in protected}
    assert original_project == snapshot(OLD_PROJECT)
    assert source_before == source_identity(ROOT)
    reference = json.loads((OLD_RUN / "report.json").read_text())["reference"]
    actual = result.frames[0].texts
    check = {"scope": "One generated fixture diagnostic; not a scored evaluation or acceptance gate.",
             "reference_origin": reference["origin"], "expected_texts": reference["expected_preview_texts"],
             "excluded_readings": reference["excluded_readings"], "actual_texts": actual,
             "exact_match": actual == reference["expected_preview_texts"],
             "excluded_readings_observed": [value for value in actual if value in reference["excluded_readings"]]}
    save("reference-check.json", check)
    receipt = {"scope": "Manual diagnostic preview of exact captured model proposal; not an investigation action, live agent run, or A0 success.",
               "created_at": datetime.now(UTC).isoformat(), "source_identity": source_before,
               "workspace": str(WORKSPACE), "project_id": project.id, "proposal_source": str(PROPOSAL),
               "proposal_sha256": sha(PROPOSAL), "graph_changed": False,
               "manual_source_binding": {"historical_media_ids": decision.action.media_ids,
                                         "copied_fixture": str(copied), "source_sha256": sha(FIXTURE)},
               "compiled": True, "actual_apple_vision_preview": True, "llm_requests": 0,
               "native_bridge": str(NATIVE), "native_bridge_sha256": sha(NATIVE),
               "model_authority_fabricated": False, "investigation_store_created": False,
               "protected_inputs_before": protected, "protected_inputs_unchanged": True,
               "original_project_unchanged": True, "production_source_unchanged": True,
               "effects_before": before, "effects_after": after,
               "usage_note": "Runtime records preview exposure only inside the new isolated workspace; no labels reviewed or scores assigned.",
               "reference_check": check, "elapsed_s": monotonic() - started, "preview_elapsed_s": result.elapsed_s}
    save("receipt.json", receipt)
    print(json.dumps({"output": str(OUT), "actual_texts": actual, "exact_match": check["exact_match"],
                      "source_unchanged": True, "elapsed_s": receipt["elapsed_s"]}), flush=True)


if __name__ == "__main__":
    main()
