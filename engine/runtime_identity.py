"""Stable source identity for native supervisor compatibility checks."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


def source_identity(package_parent: Path) -> str:
    digest = hashlib.sha256()
    for package in ("agent", "engine", "mcp_server", "spec"):
        sources = list((package_parent / package).rglob("*.py"))
        if package == "agent":
            sources.extend((package_parent / "agent/skills/packages").rglob("*.md"))
        for path in sorted(sources):
            digest.update(path.relative_to(package_parent).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def runtime_identity(data_dir: Path) -> dict[str, str | int]:
    package = Path(__file__).resolve().parent
    return {"data_dir": str(data_dir.resolve()), "python": str(Path(sys.executable).resolve()),
            "package_root": str(package), "build_id": source_identity(package.parent),
            "pid": os.getpid()}
