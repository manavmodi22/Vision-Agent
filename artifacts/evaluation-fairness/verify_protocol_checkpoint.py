"""Check the repaired evidence boundary with isolated generated fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


def rejected(action: Callable[[], object], expected: str) -> str:
    try:
        action()
    except ValueError as error:
        message = str(error)
        if expected.lower() not in message.lower():
            raise AssertionError(f"Unexpected rejection: {message}") from error
        return message
    raise AssertionError("Expected this action to be rejected")


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
    identity = source_identity(source)
    service = WorkspaceService(args.data.resolve())
    project = service.create_project("Protocol checkpoint fixture evidence", "pallets")
    service.demo(project.id)
    service.save_candidates(
        project.id, build_template("pallets", "media", "fixture-color-v1"), "Count pallets"
    )
    result = service.evaluate(project.id)
    assert result.passed and not result.promotion_eligible
    assert result.protocol_id and result.protocol_hash
    assert result.evidence_scope != "acceptance"
    promotion_rejection = rejected(
        lambda: service.deploy(project.id, 0, True), "acceptance"
    )
    trial_without_reason = rejected(
        lambda: service.deploy(project.id, 0, True, approval_scope="local_trial"),
        "reason",
    )
    trial = service.deploy(
        project.id, 0, True,
        override_reason="Verify the bounded software fixture workflow locally.",
        approval_scope="local_trial",
    )
    approval = service.approved_deployment(project.id, 0)
    assert approval.approval_scope == "local_trial"
    assert not trial["external_delivery_enabled_by_approval"]
    assert approval.protocol_id == result.protocol_id

    root = service.root(project.id)
    first = service.annotations(project.id).annotations[0]
    original = (root / first.image_path).resolve()
    repeated = []
    for index in range(10):
        path = root / f"same-pixels-{index}.png"
        shutil.copy2(original, path)
        repeated.append(first.model_copy(update={"image_path": str(path)}, deep=True))
    duplicate_rejection = rejected(
        lambda: evaluate(
            service.candidate(project.id, 0),
            EvalDataset(id="renamed-identical-software-fixtures", annotations=repeated),
            root,
        ),
        "duplicate",
    )
    oversized_run_rejection = rejected(
        lambda: service.run(project.id, 0, max_frames=501), "500"
    )
    assert len(service.events(project.id)) == 0
    assert source_identity(source) == identity, "Source changed during verification"
    payload: dict[str, Any] = {
        "source_identity": identity,
        "scope": "Generated geometric software fixtures only; not vision accuracy or human-reviewed data.",
        "sample_evaluation": result.model_dump(mode="json"),
        "promotion_rejection": promotion_rejection,
        "trial_without_reason_rejection": trial_without_reason,
        "explicit_local_trial": trial,
        "deployment": approval.model_dump(mode="json"),
        "renamed_duplicate_rejection": duplicate_rejection,
        "oversized_run_rejection": oversized_run_rejection,
        "recorded_events": len(service.events(project.id)),
        "real_models_called": False,
        "user_projects_modified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
