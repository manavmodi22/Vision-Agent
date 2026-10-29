"""Fail closed while a human handoff has an uncertain or unfinished commit."""
import json
from pathlib import Path

from agent.machine import AgentConflict


def assert_handoff_settled(root: Path) -> None:
    path = root / "review-handoff.json"
    if path.exists() and json.loads(path.read_text()).get("status") in {"previewing", "committing", "aborting"}:
        raise AgentConflict("Draft handoff is in progress or requires recovery. Refresh its handoff status before continuing.")


def assert_handoff_mutable(root: Path) -> None:
    """Preview edits may invalidate safely; incomplete commits need recovery first."""
    path = root / "review-handoff.json"
    if path.exists() and json.loads(path.read_text()).get("status") in {"committing", "aborting"}:
        raise AgentConflict("Recover the pending draft handoff before changing this project's inputs.")
