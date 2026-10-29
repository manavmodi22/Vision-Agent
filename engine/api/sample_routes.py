"""One-click public reference media for the agent's first build."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from engine.service import WorkspaceService
from engine.store.models import Project

SAMPLE_ID = "nvidia-warehouse-real"
VIDEO = "MTMC_Tracking_2026/test/Warehouse_026/videos/Camera_0000.mp4"
REVISION = "2cbe9563cbe9f47f846e5c871ee994572bbbc60e"
SOURCE = f"https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces/tree/{REVISION}"


class SampleMedia(BaseModel):
    id: str = SAMPLE_ID
    name: str = "Warehouse footage"
    description: str = "Try your goal on 20 frames from a real NVIDIA warehouse recording. Labels still need review."
    source_kind: str = "recorded_video"
    origin: str = "NVIDIA Physical AI Smart Spaces — Warehouse 026"
    license: str = "CC-BY-4.0"
    source_url: str = SOURCE
    synthetic: bool = False
    available: bool


def extract_sample(path: Path, destination: Path) -> list[str]:
    import cv2

    capture = cv2.VideoCapture(str(path))
    frames: list[str] = []
    try:
        if not capture.isOpened():
            raise ValueError("The public warehouse recording could not be opened")
        for index in range(20):
            timestamp = 33 + index * 0.75
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, pixels = capture.read()
            target = destination / f"warehouse-{timestamp:06.2f}s.png"
            if not ok or not cv2.imwrite(str(target), pixels):
                raise ValueError(f"Could not read the public recording at {timestamp:g} seconds")
            frames.append(str(target))
        return frames
    finally:
        capture.release()


def sample_path(service: WorkspaceService) -> Path:
    return service.repository.root / "datasets/nvidia-smartspaces" / VIDEO


def catalog(service: WorkspaceService) -> list[SampleMedia]:
    path = sample_path(service)
    manifest = path.parents[4] / "manifest.json"
    return [SampleMedia(available=path.is_file() and manifest.is_file())]


def import_sample(service: WorkspaceService, project_id: str, sample_id: str) -> Project:
    if sample_id != SAMPLE_ID:
        raise ValueError("Unknown public sample")
    path = sample_path(service)
    manifest_path = path.parents[4] / "manifest.json"
    if not path.is_file() or not manifest_path.is_file():
        raise ValueError("The public warehouse sample is not installed on this Mac. Attach images or video to start.")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("revision") != REVISION or manifest.get("license") != "CC-BY-4.0":
        raise ValueError("Public sample provenance differs from the verified dataset revision")
    item = next((item for item in manifest.get("files", []) if item.get("path") == VIDEO), None)
    if item is None:
        raise ValueError("Public sample is absent from the download manifest")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != item.get("sha256"):
        raise ValueError("Public sample bytes differ from their download manifest")
    with service.repository.lock:
        project = service.get_project(project_id)
        provenance = service.root(project_id) / "sample-source.json"
        if provenance.is_file() and json.loads(provenance.read_text()).get("sample_id") == SAMPLE_ID:
            return project
        if project.media:
            raise ValueError("Use the public sample in a new app so it stays separate from your own images")
        with tempfile.TemporaryDirectory(prefix="sample-import-", dir=service.repository.root) as temporary:
            frames = extract_sample(path, Path(temporary))
            project = service.import_media(project_id, frames)
        project.data_origin = f"NVIDIA Physical AI Smart Spaces, real Warehouse 026; CC-BY-4.0; revision {REVISION}"
        project.synthetic = False
        service.repository.save(project)
        provenance.write_text(json.dumps({
            "sample_id": SAMPLE_ID, "source_url": SOURCE, "video": VIDEO, "sha256": digest,
            "revision": REVISION, "license": "CC-BY-4.0", "attribution": "NVIDIA Physical AI Smart Spaces",
            "synthetic": False, "frame_count": len(project.media), "reviewed": False,
            "source_timestamps_s": [33 + index * 0.75 for index in range(20)],
        }, indent=2))
        return project


def build_router(service: WorkspaceService) -> APIRouter:
    router = APIRouter()

    @router.get("/samples/catalog")
    def samples() -> list[SampleMedia]:
        return catalog(service)

    @router.post("/projects/{project_id}/samples/{sample_id}/import")
    def load_sample(project_id: str, sample_id: str) -> Project:
        return import_sample(service, project_id, sample_id)

    return router
