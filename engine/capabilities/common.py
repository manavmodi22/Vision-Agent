"""Cheap, local-only evidence helpers; never import learned model runtimes."""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from spec.capabilities import CapabilityEvidence, CapabilityLicense, CapabilityProvenance


def now() -> str:
    return datetime.now(UTC).isoformat()


def evidence(kind: str, subject: str, passed: bool | None, detail: str,
             metadata: dict[str, JsonValue] | None = None) -> CapabilityEvidence:
    return CapabilityEvidence.model_validate({"kind": kind, "subject": subject,
        "outcome": "unknown" if passed is None else "pass" if passed else "fail",
        "detail": detail, "observed_at": now(), "metadata": metadata or {}})


def package_evidence(name: str) -> CapabilityEvidence:
    try:
        present = importlib.util.find_spec(name) is not None
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            version = None
    except (ImportError, ValueError):
        present, version = False, None
    return evidence("package", name, present, "Import discovery only; package was not loaded", {"version": version})


def file_evidence(path: Path) -> CapabilityEvidence:
    try:
        stat = path.stat()
        if not path.is_file():
            return evidence("file", str(path), False, "Not a regular file")
        return evidence("file", str(path), True, "File presence does not verify model inference or weights",
                        {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    except OSError:
        return evidence("file", str(path), False, "Required local file is missing or unreadable")


def small_hash(path: Path) -> str | None:
    try:
        if path.stat().st_size <= 2 * 1024 * 1024:
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    return None


def code_provenance(path: Path) -> CapabilityProvenance:
    digest = small_hash(path)
    return CapabilityProvenance(scope="bundled_code", hashes={path.name: digest} if digest else {},
                                notes=["Hash identifies adapter source, not model weights or a hardware smoke test."])


def app_license() -> CapabilityLicense:
    return CapabilityLicense(identifier="Project source; license unspecified", status="unverified",
        notes=["No license has been assigned to this user-owned repository. This catalog does not grant distribution rights."])


def host() -> dict[str, JsonValue]:
    try:
        memory: int | None = int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (ValueError, OSError):
        memory = None
    return {"os": platform.system(), "os_version": platform.release(), "architecture": platform.machine(),
            "python": sys.version.split()[0], "cpu_count": os.cpu_count(), "memory_bytes": memory,
            "mps_available": None, "note": "No accelerator runtime loaded during discovery."}
