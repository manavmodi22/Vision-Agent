"""Pinned second-scene benchmark inputs; never changes application review flags."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import httpx

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "artifacts/scene-holdout"
REVISION = "2cbe9563cbe9f47f846e5c871ee994572bbbc60e"
SCENE = "MTMC_Tracking_2025/val/Warehouse_016"
CAMERA = "Camera_01"
DATA = Path.home() / "Library/Application Support/VisionApp/datasets/nvidia-smartspaces"
metadata = json.loads((OUT / "upstream-tree.json").read_text())
requested = {
    f"{SCENE}/calibration.json",
    f"{SCENE}/ground_truth.json",
    f"{SCENE}/videos/{CAMERA}.mp4",
}
entries = [entry for entry in metadata["scene"] + metadata["videos"] if entry["path"] in requested]
assert len(entries) == 3
receipts = []
with httpx.Client(follow_redirects=True, timeout=180) as client:
    for item in entries:
        path = DATA / item["path"]
        url = f"https://huggingface.co/datasets/nvidia/PhysicalAI-SmartSpaces/resolve/{REVISION}/{item['path']}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            partial = path.with_suffix(path.suffix + ".partial")
            with client.stream("GET", url) as response, partial.open("wb") as stream:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    stream.write(chunk)
            assert partial.stat().st_size == item["size"]
            assert (
                hashlib.file_digest(partial.open("rb"), "sha256").hexdigest() == item["lfs"]["oid"]
            )
            partial.replace(path)
        digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        assert digest == item["lfs"]["oid"] and path.stat().st_size == item["size"]
        receipts.append({"path": str(path), "url": url, "bytes": item["size"], "sha256": digest})
        print(f"Verified {item['path']}: {item['size']} bytes", flush=True)
frames_dir = DATA / SCENE / "benchmark-30" / CAMERA
frames_dir.mkdir(parents=True, exist_ok=True)
video = DATA / SCENE / "videos" / f"{CAMERA}.mp4"
capture = cv2.VideoCapture(str(video))
assert capture.isOpened()
total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
fps = capture.get(cv2.CAP_PROP_FPS)
indices = [round(i * (total - 1) / 29) for i in range(30)]
ground_truth = json.loads((DATA / SCENE / "ground_truth.json").read_text())
records = []
try:
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, image = capture.read()
        assert ok
        path = frames_dir / f"{CAMERA}-{index:06d}.png"
        assert cv2.imwrite(str(path), image)
        height, width = image.shape[:2]
        detections = []
        for item in ground_truth[str(index)]:
            label = item.get("object type", item.get("object_type", "")).lower()
            box = item.get("2d bounding box visible", item.get("2d_bounding_box_visible", {})).get(
                CAMERA
            )
            if label != "person" or box is None:
                continue
            box = [
                max(0.0, min(1.0, value / (width if i % 2 == 0 else height)))
                for i, value in enumerate(box)
            ]
            if box[0] < box[2] and box[1] < box[3]:
                detections.append({"label": label, "confidence": 1.0, "box": box})
        records.append(
            {
                "image_path": str(path),
                "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "frame_index": index,
                "timestamp_s": index / fps,
                "source_scene": SCENE,
                "source_camera": CAMERA,
                "detections": detections,
                "reviewed": False,
                "ground_truth_origin": "NVIDIA IsaacSim published automatic labels",
            }
        )
finally:
    capture.release()
protocol = {
    "schema_version": 1,
    "created_at": datetime.now(UTC).isoformat(),
    "dataset": "nvidia/PhysicalAI-SmartSpaces",
    "revision": REVISION,
    "license": "CC-BY-4.0",
    "attribution": "NVIDIA Physical AI Smart Spaces, Wang et al. (2026)",
    "scene": SCENE,
    "camera": CAMERA,
    "synthetic": True,
    "source_receipts": receipts,
    "comparison": {
        "task": "person detection/count",
        "models": ["owlv2-base-patch16", "rtdetr-v2-r18", "yolox-s-onnx-coco"],
        "min_conf": 0.15,
        "matching_iou": 0.5,
        "target_recall": 0.8,
        "frame_indices": indices,
    },
    "scope": "New source scene distinct from previously tuned Warehouse_015. Fixed samples and thresholds before inference. Published synthetic labels, not human reviewed or an independent real-world deployment benchmark.",
    "promotion_eligible": False,
    "label_review_status": "unreviewed_published_synthetic",
    "annotations": records,
}
path = OUT / "protocol.json"
assert not path.exists(), "Do not overwrite a frozen protocol"
path.write_text(json.dumps(protocol, indent=2) + "\n")
(OUT / "protocol.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n")
print(
    json.dumps(
        {
            "frames": len(records),
            "person_boxes": sum(len(a["detections"]) for a in records),
            "protocol_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
)
