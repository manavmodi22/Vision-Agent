"""Version native reading evidence without claiming access to Apple's weights."""
from __future__ import annotations

import hashlib
import os
import platform
from pathlib import Path

from pydantic import JsonValue

READING_REQUEST_POLICY_VERSION = "apple-vision-en-us-v2"


def native_reading_identity() -> dict[str, JsonValue]:
    """Bind actual bridge bytes and system/request versions, not path or mtime.

    Missing bridges remain representable for offline workflow authoring. Runtime
    reading still rejects them; this value is not an inference-readiness claim.
    """
    bridge = Path(os.environ.get("VISION_APP_BINARY", ""))
    bridge_hash = "missing"
    if bridge.is_file():
        content = hashlib.sha256()
        try:
            with bridge.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    content.update(chunk)
        except OSError as exc:
            raise ValueError(f"Cannot verify native reading bridge content: {exc}") from exc
        bridge_hash = content.hexdigest()
    return {
        "adapter": "apple-vision",
        "identity_scope": "system_framework_versioned",
        "request_policy": READING_REQUEST_POLICY_VERSION,
        "bridge_sha256": bridge_hash,
        "macos": platform.mac_ver()[0],
        "kernel": platform.release(),
        "kernel_build": platform.version(),
        "architecture": platform.machine(),
    }
