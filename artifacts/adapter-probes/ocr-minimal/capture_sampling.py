"""No learned inference: capture crop/resize tensors for native-build parity audit."""

import argparse
import json
from pathlib import Path

import numpy as np
from image_ops import crop_quad, recognition_input
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
rows = json.loads((Path(__file__).parent / "image-only-result.json").read_text())["results"]
tensors = {}
for row in rows:
    with Image.open(row["path"]) as image:
        bgr = np.array(image.convert("RGB"))[:, :, ::-1].copy()
    for i, observation in enumerate(row["observations"]):
        key = row["id"] + "-" + str(i)
        crop = crop_quad(bgr, np.array(observation["polygon_pixels"]))
        tensors[key] = recognition_input(crop)
np.savez_compressed(args.output, **tensors)
