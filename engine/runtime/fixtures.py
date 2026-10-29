"""Generate original synthetic fixtures with exact labels and explicit provenance."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from engine.models.fixture import PALETTE
from spec.models import Annotation, Detection, EvalDataset


def generate_demo(project_root: Path) -> EvalDataset:
    media = project_root / "media"
    media.mkdir(parents=True, exist_ok=True)
    zones_dir = project_root / "zones"
    zones_dir.mkdir(parents=True, exist_ok=True)
    zones = [{"id": name, "polygon": [[i / 4, 0], [(i + 1) / 4, 0],
             [(i + 1) / 4, 1], [i / 4, 1]]} for i, name in enumerate("ABCD")]
    (zones_dir / "lanes.json").write_text(json.dumps({"zones": zones}, indent=2))
    annotations: list[Annotation] = []
    width, height = 640, 400
    for index in range(16):
        image = Image.new("RGB", (width, height), (22, 31, 43))
        draw = ImageDraw.Draw(image)
        draw.text((18, 12), f"SYNTHETIC FIXTURE {index + 1:02d} - NOT REAL WAREHOUSE IMAGERY", fill=(200, 212, 225))
        detections: list[Detection] = []
        for lane, name in enumerate("ABCD"):
            left = lane * 160
            draw.line((left, 42, left, height - 12), fill=(65, 77, 92), width=2)
            draw.text((left + 20, 45), f"LANE {name}", fill=(150, 171, 194))
            count = (index + lane * 2) % 4
            for row in range(count):
                x0, y0 = left + 35, 90 + row * 90
                x1, y1 = x0 + 90, y0 + 55
                draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=PALETTE["pallet"])
                # Interior dark lines do not split the connected rectangular region.
                draw.line((x0 + 8, y0 + 16, x1 - 9, y0 + 16), fill=(22, 90, 65), width=3)
                detections.append(Detection(label="pallet", confidence=1,
                    box=[x0 / width, y0 / height, x1 / width, y1 / height], zone=name))
        path = media / f"synthetic-{index + 1:02d}.png"
        image.save(path)
        annotations.append(Annotation(image_path=str(path), detections=detections, reviewed=True))
    dataset = EvalDataset(id="synthetic-lanes-v1", annotations=annotations)
    (project_root / "synthetic-provenance.json").write_text(json.dumps({
        "type": "synthetic", "generator": "VisionApp original deterministic rectangle fixtures",
        "license": "CC0-1.0", "purpose": "Software verification only; not warehouse model validation",
        "count": len(annotations), "labels": "Exact generator geometry, not human reviewed real imagery",
    }, indent=2))
    return dataset
