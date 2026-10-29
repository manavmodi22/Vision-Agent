"""Reproduce the evidence-scope gap using only generated software fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    if args.data.exists() or args.output.exists():
        raise ValueError("Use new output paths; prior evidence is retained")
    sys.path.insert(0, str(source))
    import engine
    from agent.templates import build_template
    from engine.eval import evaluate
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService
    from spec.models import EvalDataset

    assert Path(engine.__file__).resolve().is_relative_to(source)
    service = WorkspaceService(args.data.resolve())
    project = service.create_project("Pre-protocol fixture evidence", "pallets")
    service.demo(project.id)
    service.save_candidates(
        project.id, build_template("pallets", "media", "fixture-color-v1"), "Count pallets"
    )
    result = service.evaluate(project.id)
    approval = service.deploy(project.id, 0, True)
    root = service.root(project.id)
    first = service.annotations(project.id).annotations[0]
    original = (root / first.image_path).resolve()
    repeated = []
    for index in range(10):
        path = root / f"same-pixels-{index}.png"
        shutil.copy2(original, path)
        repeated.append(first.model_copy(update={"image_path": str(path)}, deep=True))
    duplicate_result = evaluate(
        service.candidate(project.id, 0),
        EvalDataset(id="renamed-identical-software-fixtures", annotations=repeated),
        root,
    )
    payload = {
        "source_commit": "4ffa46653d1b6e16af146ecdf8363942fc21259c",
        "source_identity": source_identity(source),
        "scope": "Generated geometric software fixtures only; not vision accuracy or human-reviewed data.",
        "ordinary_approval_on_fixture": {
            "numeric_passed": result.passed,
            "sample_count": result.sample_count,
            "response": approval,
            "deployment": json.loads((root / "deployment.json").read_text()),
            "interpretation": "The legacy approval has no independent-acceptance versus local-trial distinction.",
        },
        "renamed_identical_images": {
            "unique_original_pixels": 1,
            "distinct_filenames": 10,
            "reported_sample_count": duplicate_result.sample_count,
            "numeric_passed": duplicate_result.passed,
            "interpretation": "Legacy evaluation accepts repeated content under distinct paths.",
        },
        "recorded_events": len(service.events(project.id)),
        "real_models_called": False,
        "user_projects_modified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
