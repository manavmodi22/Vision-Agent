"""Create one explicitly synthetic UI test using the installed engine package.

The build result is seeded through the normal scoring handler after actual
fixture preview/evaluation. No planner, learned detector or user labels are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agent.templates import build_template
from engine.builds.manager import BuildManager
from engine.runtime_identity import source_identity
from engine.service import WorkspaceService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError("Retain prior QA receipts; use a new path")
    service = WorkspaceService(args.workspace.resolve())
    project = service.create_project("QA · evaluation controls · synthetic", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1")[:1],
                            "Software test of evaluation controls using generated rectangles.")
    score = service.evaluate(project.id)
    preview = service.preview(project.id)
    manager = BuildManager(service)
    record = manager.store.create(project.id, "Software QA only: inspect generated fixture evaluation controls.")
    manager._scored(project.id, record.view.id, [score], 0, preview)
    root = service.root(project.id)
    import engine
    receipt = {
        "project_id": project.id, "project_root": str(root), "name": project.name,
        "purpose": "Temporary generated software QA project; no human-authored data.",
        "runtime_source_identity": source_identity(Path(engine.__file__).resolve().parent.parent),
        "annotations_sha256": hashlib.sha256((root / "annotations.json").read_bytes()).hexdigest(),
        "planner_calls": 0, "learned_model_calls": 0, "recorded_events": len(service.events(project.id)),
        "expected_phase": "evidence", "promotion_eligible": score.promotion_eligible,
    }
    (root / "qa-ownership.json").write_text(json.dumps(receipt, indent=2) + "\n")
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
