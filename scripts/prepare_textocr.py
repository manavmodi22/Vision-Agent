"""Freeze a small public TextOCR diagnostic sample without changing app review state.

Annotations are CC-BY-4.0. Images retain individual Open Images source metadata.
The generated manifest is a diagnostic dataset, not independent acceptance data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
from urllib.request import urlopen

from PIL import Image

LABEL_URL = "https://dl.fbaipublicfiles.com/textvqa/data/textocr/TextOCR_0.1_val.json"
LABEL_SHA = "0d04c1c9f5ba99e90be5b0df9ab34f6237b3fbc55443f263133d5c49b6435918"
METADATA_URL = "https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv"
SEED = "visionapp-textocr-diagnostic-v1"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, target: Path, limit: int) -> bytes:
    if target.exists():
        if target.stat().st_size > limit:
            raise ValueError("Cached file exceeds download budget")
        return target.read_bytes()
    with urlopen(url, timeout=90) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds byte budget")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_bytes(data)
    temporary.replace(target)
    return data


def prepare(root: Path, count: int, output: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    labels = download(LABEL_URL, root / "TextOCR_0.1_val.json", 50_000_000)
    if digest(labels) != LABEL_SHA:
        raise ValueError("Public label bytes changed; inspect before changing the pinned digest")
    data = json.loads(labels)
    ids = sorted(data["imgs"], key=lambda value: digest((SEED + value).encode()))[:count]
    selection = {"seed": SEED, "image_ids": ids, "annotation_sha256": LABEL_SHA,
                 "selection": "First N image IDs ordered by SHA256(seed + ID); before inference",
                 "maximum_word_crops_per_image": 5,
                 "crop_selection": "ASCII, nonempty, legible published words ordered by SHA256(seed + annotation ID)"}
    selection_path = root / "selection.json"
    if selection_path.exists() and json.loads(selection_path.read_text()) != selection:
        raise ValueError("Selection already frozen; use another directory for a different sample")
    selection_path.write_text(json.dumps(selection, indent=2) + "\n")
    metadata_path = root / "selected-image-metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        # Streaming preserves attribution without downloading the full image collection.
        metadata = {}
        with urlopen(METADATA_URL, timeout=90) as response:
            for row in csv.DictReader(io.TextIOWrapper(response, encoding="utf-8")):
                if row["ImageID"] in ids:
                    metadata[row["ImageID"]] = row
                if len(metadata) == len(ids):
                    break
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    rows = []
    for identifier in ids:
        if identifier not in metadata:
            raise ValueError(f"Source metadata absent for {identifier}")
        meta = metadata[identifier]
        if meta.get("License") not in {"https://creativecommons.org/licenses/by/2.0/", "http://creativecommons.org/licenses/by/2.0/"}:
            raise ValueError(f"Unreviewed source license: {identifier} {meta.get('License')}")
        source = f"https://open-images-dataset.s3.amazonaws.com/train/{identifier}.jpg"
        image_path = root / "images" / f"{identifier}.jpg"
        image_bytes = download(source, image_path, 10_000_000)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        original = data["imgs"][identifier]
        rotation = float(meta.get("Rotation") or 0)
        # TextOCR coordinates describe these downloaded pixels, including sideways text.
        # Open Images rotation is source metadata; applying it would move the labels.
        if image.size != (original["width"], original["height"]):
            raise ValueError(f"Image dimensions differ from published annotation space: {identifier} {image.size}")
        candidates = [data["anns"][key] for key in data["imgToAnns"][identifier]]
        eligible = [a for a in candidates if a["utf8_string"].isascii() and a["utf8_string"].strip() not in {"", "."}]
        selected = sorted(eligible, key=lambda a: digest((SEED + a["id"]).encode()))[:5]
        crops = []
        for annotation in selected:
            x, y, w, h = annotation["bbox"]
            padding = max(2, min(w, h) * .05)
            bounds = (max(0, math.floor(x - padding)), max(0, math.floor(y - padding)),
                      min(image.width, math.ceil(x + w + padding)), min(image.height, math.ceil(y + h + padding)))
            if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                raise ValueError("Invalid published crop geometry")
            crop_path = root / "crops" / f"{annotation['id']}.png"
            crop_path.parent.mkdir(exist_ok=True)
            image.crop(bounds).save(crop_path)
            crops.append({"id": annotation["id"], "path": str(crop_path.resolve()),
                          "sha256": digest(crop_path.read_bytes()), "crop_xyxy": bounds,
                          "published_polygon": annotation["points"], "expected_text": annotation["utf8_string"],
                          "reviewed": False})
        rows.append({"id": identifier, "source_url": source, "source_metadata": meta,
                     "original_sha256": digest(image_bytes), "original_bytes": len(image_bytes),
                     "annotation_dimensions": image.size, "source_rotation_degrees": rotation, "applied_rotation_degrees": 0,
                     "published_word_count": len(candidates), "illegible_word_count": sum(a["utf8_string"] == "." for a in candidates),
                     "selected_crops": crops})
        print(identifier, len(crops), "crops", flush=True)
    manifest = {"schema_version": "0.1", "dataset": "TextOCR v0.1 validation", "source_page": "https://textvqa.org/textocr/dataset/",
                "annotation_source": LABEL_URL, "annotation_sha256": LABEL_SHA,
                "annotation_license": "CC-BY-4.0", "annotation_attribution": "TextOCR authors, Singh et al., CVPR 2021",
                "image_metadata_source": METADATA_URL, "image_license_status": "Official Open Images metadata declarations; individual Flickr pages not independently reverified",
                "selection": selection, "images": rows, "reviewed": False,
                "scope": "Word crop recognition diagnostic. Full-image spotting, warehouse accuracy and independent acceptance are not established.",
                "limitations": ["Public validation labels are not human review in this app", "Pretraining overlap unknown", "Scene grouping and near-duplicate audit pending", "ASCII-only crop subset; no claim for non-English text", "Source images remain local and are not redistributed"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"images": len(rows), "crops": sum(len(r["selected_crops"]) for r in rows), "manifest": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20, choices=range(1, 121))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.root, args.count, args.output)
