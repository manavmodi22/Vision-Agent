"""Package the locally built extension and its notices into an isolated wheel."""

import base64
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[2] / ".visionapp/adapter-probes/ocr-minimal"
SOURCE = (
    HERE.parents[2] / json.loads((HERE / "opencv-build-source.json").read_text())["source_path"]
)
extensions = list((WORK / "opencv-build/lib").rglob("cv2*.so"))
if len(extensions) != 1:
    raise ValueError(f"Expected one built extension, found {extensions}")
extension = extensions[0]
name = "opencv_image_only"
version = "4.10.0+visionimage1"
dist = f"{name}-{version}.dist-info"
files = {
    extension.name: extension.read_bytes(),
    f"{dist}/METADATA": (
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        "Summary: Local OpenCV core and imgproc only, no video or GUI modules\n"
        "License: Apache-2.0 AND BSD-3-Clause\nRequires-Python: >=3.12,<3.13\nRequires-Dist: numpy>=2,<3\n"
    ).encode(),
    f"{dist}/WHEEL": b"Wheel-Version: 1.0\nGenerator: local-isolated-probe\nRoot-Is-Purelib: false\nTag: cp312-cp312-macosx_11_0_arm64\n",
    f"{dist}/LICENSE-opencv": (SOURCE / "LICENSE").read_bytes(),
    f"{dist}/LICENSE-carotene": (SOURCE / "3rdparty/carotene/src/common.cpp")
    .read_text()
    .split("*/", 1)[0]
    .encode()
    + b"*/\n",
    f"{dist}/LICENSE-flatbuffers": (SOURCE / "3rdparty/flatbuffers/LICENSE.txt").read_bytes(),
    f"{dist}/NOTICE": (
        b"Built from OpenCV4.10.0 commit71d3237a093b60a27601c20e9ee6c3e52154e8b1.\n"
        b"Only core,imgproc,python3 enabled. Static Carotene BSD-3-Clause HAL included.\n"
        b"Build recipe and archive provenance are retained in the probe artifacts.\n"
        b"No upstream sources were modified. This wheel is a local prototype artifact, not a published release.\n"
    ),
}
records = []
for path, content in files.items():
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
    records.append((path, f"sha256={digest}", len(content)))
records.append((f"{dist}/RECORD", "", ""))
buffer = io.StringIO()
csv.writer(buffer, lineterminator="\n").writerows(records)
files[f"{dist}/RECORD"] = buffer.getvalue().encode()
wheel = WORK / f"{name}-{version}-cp312-cp312-macosx_11_0_arm64.whl"
with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path, content in files.items():
        archive.writestr(path, content)
receipt = {
    "path": str(wheel),
    "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    "bytes": wheel.stat().st_size,
    "extension_sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
    "distribution": name,
    "version": version,
    "tag": "cp312-cp312-macosx_11_0_arm64",
}
(HERE / "opencv-image-wheel.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt))
