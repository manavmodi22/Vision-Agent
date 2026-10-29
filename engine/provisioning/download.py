"""Size/hash-bound streaming of registry artifacts with allowlisted redirects."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from urllib.parse import urljoin, urlsplit

import httpx

from engine.provisioning.registry import DOWNLOAD_HOSTS
from spec.provisioning import ProvisioningArtifact


def check_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS
            or parsed.port not in {None, 443} or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("Artifact redirect is outside the reviewed public HTTPS sources")


def download_artifact(artifact: ProvisioningArtifact, target: Path, *, deadline: float,
                      stopped: Event, progress: Callable[[int], None], client: httpx.Client) -> None:
    if target.exists() or target.is_symlink():
        raise ValueError("Staging artifact already exists")
    if Path(artifact.filename).name != artifact.filename or artifact.filename in {".", ".."}:
        raise ValueError("Invalid registry artifact filename")
    url = artifact.source_url
    try:
        for _ in range(6):
            check_url(url)
            if stopped.is_set() or time.monotonic() >= deadline:
                raise TimeoutError("Provisioning stopped or exceeded its reviewed time budget")
            remaining = max(.01, deadline - time.monotonic())
            timeout = httpx.Timeout(connect=min(5, remaining), read=min(1, remaining), write=min(5, remaining), pool=min(1, remaining))
            with client.stream("GET", url, headers={"Accept-Encoding": "identity"}, timeout=timeout) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Artifact redirect has no destination")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") not in {"", "identity"}:
                    raise ValueError("Unexpected encoded artifact body")
                declared = response.headers.get("content-length")
                if declared is not None and int(declared) != artifact.expected_bytes:
                    raise ValueError("Artifact Content-Length differs from the reviewed exact size")
                digest, received = hashlib.sha256(), 0
                with target.open("xb") as output:
                    for chunk in response.iter_raw():
                        if stopped.is_set() or time.monotonic() >= deadline:
                            raise TimeoutError("Provisioning stopped or exceeded its reviewed time budget")
                        received += len(chunk)
                        if received > artifact.expected_bytes:
                            raise ValueError("Artifact exceeds the reviewed exact byte limit")
                        output.write(chunk)
                        digest.update(chunk)
                        progress(received)
                    output.flush()
                if received != artifact.expected_bytes or digest.hexdigest() != artifact.expected_sha256:
                    raise ValueError("Downloaded artifact does not match the reviewed size and SHA256")
                return
        raise ValueError("Artifact exceeded the five-redirect bound")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
