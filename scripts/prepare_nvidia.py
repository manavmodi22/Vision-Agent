"""Create reproducible local projects from NVIDIA CC-BY-4.0 public footage.

Downloads are pinned to the recorded revision. Original GT is used only for an
explicit benchmark. App annotations remain unreviewed and cannot pass deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import httpx

from engine.service import WorkspaceService
from engine.store.models import Message
from engine.store.repository import atomic_model
from spec.models import Annotation, Detection, EvalDataset, PipelineSpec

REPO = "nvidia/PhysicalAI-SmartSpaces"
REVISION = ""  # Resolve once and pin in the local manifest on first acquisition.
SYNTHETIC = "MTMC_Tracking_2025/val/Warehouse_015"
REAL = "MTMC_Tracking_2026/test/Warehouse_026"


def obtain(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        revision = manifest.get("revision") or client.get(
            f"https://huggingface.co/api/datasets/{REPO}"
        ).raise_for_status().json()["sha"]
        paths = ["README.md", f"{SYNTHETIC}/ground_truth.json", f"{SYNTHETIC}/calibration.json",
                 f"{SYNTHETIC}/videos/Camera_01.mp4", f"{REAL}/calibration.json",
                 f"{REAL}/videos/Camera_0000.mp4"]
        files = []
        for path in paths:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://huggingface.co/datasets/{REPO}/resolve/{revision}/{path}"
            if not target.exists():
                temporary = target.with_suffix(".partial")
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as stream:
                        for chunk in response.iter_bytes():
                            stream.write(chunk)
                temporary.replace(target)
            files.append({"path": path, "url": url, "bytes": target.stat().st_size,
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        manifest = {"dataset": REPO, "revision": revision, "license": "CC-BY-4.0",
                    "attribution": "NVIDIA Physical AI Smart Spaces",
                    "synthetic": SYNTHETIC, "real_unlabelled": REAL, "files": files}
        manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def extract(video: Path, destination: Path, count: int) -> list[tuple[int, Path, int, int]]:
    destination.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"Cannot decode {video}")
    frames: list[tuple[int, Path, int, int]] = []
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        for i in range(count):
            index = round(i * (total - 1) / (count - 1))
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"Cannot decode frame {index}")
            path = destination / f"{video.stem}-frame-{index:06d}.png"
            if not cv2.imwrite(str(path), frame):
                raise ValueError(f"Cannot save {path}")
            height, width = frame.shape[:2]
            frames.append((index, path, width, height))
    finally:
        capture.release()
    return frames


def baseline_spec() -> PipelineSpec:
    return PipelineSpec.model_validate({
        "spec_version": "0.1", "name": "NVIDIA people-and-forklift baseline",
        "inputs": {"source": {"type": "image_folder", "path": "media"}},
        "blocks": [
            {"id": "sample", "type": "frame_sample", "params": {"fps": 2}, "in": {"frames": "$inputs.source"}},
            {"id": "det", "type": "detect_open_vocab", "params": {
                "model": "owlv2-base-patch16", "classes": ["person", "forklift"], "min_conf": 0.15},
             "in": {"image": "$sample.frame"}},
            {"id": "count", "type": "count_per_zone", "in": {"dets": "$det.dets"}},
            {"id": "rule", "type": "rule", "params": {"when": "count >= 1"}, "in": {"value": "$count.counts"}},
            {"id": "out", "type": "sink_event", "in": {"event": "$rule.event"}},
        ], "eval": {"set": "nvidia-published-labels", "metric": "recall", "target": 0.8},
    })


def seed(data_dir: Path) -> list[str]:
    service = WorkspaceService(data_dir)
    dataset_root = data_dir / "datasets/nvidia-smartspaces"
    manifest = obtain(dataset_root)
    ground_truth = json.loads((dataset_root / SYNTHETIC / "ground_truth.json").read_text())
    created = []
    for synthetic, count, scene, camera in [(True, 30, SYNTHETIC, "Camera_01"),
                                           (False, 20, REAL, "Camera_0000")]:
        name = "NVIDIA warehouse · annotated synthetic" if synthetic else "NVIDIA warehouse · real footage"
        existing = next((p for p in service.list_projects() if p.name == name), None)
        if existing:
            created.append(existing.id)
            continue
        project = service.create_project(name)
        root = service.root(project.id)
        frames = extract(dataset_root / scene / "videos" / f"{camera}.mp4", root / "media", count)
        annotations = []
        for index, path, width, height in frames:
            detections = []
            if synthetic:
                for item in ground_truth[str(index)]:
                    label = item.get("object type", item.get("object_type", "")).lower()
                    bounds = item.get("2d bounding box visible", item.get("2d_bounding_box_visible", {})).get(camera)
                    if label not in {"person", "forklift"} or bounds is None:
                        continue
                    box = [max(0., min(1., value / (width if i % 2 == 0 else height)))
                           for i, value in enumerate(bounds)]
                    if box[0] < box[2] and box[1] < box[3]:
                        detections.append(Detection(label=label, confidence=1, box=box))
            annotations.append(Annotation(image_path=str(path), detections=detections, reviewed=False))
        project.media = [str(path) for _, path, _, _ in frames]
        project.synthetic = synthetic
        project.fixture = False
        project.data_origin = f"NVIDIA PhysicalAI-SmartSpaces · {scene} · CC-BY-4.0"
        project.messages = [Message(role="system", content=(
            "Imported published synthetic person/forklift labels. Review them before deployment. "
            "This is an inference baseline, not a pallet, damage or barcode accuracy validation."
            if synthetic else "Real NVIDIA warehouse footage. Published ground truth is withheld; "
            "labels are empty and unreviewed. No accuracy claims are available."
        ))]
        service.repository.save(project)
        atomic_model(root / "annotations.json", EvalDataset(id=f"nvidia-{project.id}", annotations=annotations))
        if synthetic:
            service.save_candidates(project.id, [baseline_spec()], "NVIDIA synthetic person/forklift baseline")
        else:
            from agent.templates import build_template
            candidates = build_template("pallets", "media", "owlv2-base-patch16")
            candidates[0].blocks[1].params["min_conf"] = 0.15
            service.save_candidates(project.id, candidates, "Explore pallets on real warehouse footage; no labelled accuracy yet")
        (root / "source-provenance.json").write_text(json.dumps({**manifest, "scene": scene,
            "camera": camera, "frames": [index for index, _, _, _ in frames],
            "label_status": "published synthetic labels; not human reviewed" if synthetic else "unlabelled",
            "derivation": "Video frames decoded to PNG; boxes normalized to xyxy; person/forklift classes only",
        }, indent=2))
        created.append(project.id)
        print(project.id, name, count, "frames", flush=True)
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Library/Application Support/VisionApp")
    options = parser.parse_args()
    seed(options.data_dir)
