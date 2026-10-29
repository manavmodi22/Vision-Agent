"""Reproducible local core/imgproc/Python-only build, with network denied."""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = ROOT / ".visionapp/adapter-probes/ocr-minimal"
SOURCE = ROOT / json.loads((HERE / "opencv-build-source.json").read_text())["source_path"]
BASE = Path(sys.base_prefix)
CMAKE = WORK / "build-tools/bin/cmake"
BUILD = WORK / "opencv-build"
POLICY = "(version 1)(allow default)(deny network*)"
configuration = {
    "OPENCV_VCSVERSION": "4.10.0-71d3237a093b60a27601c20e9ee6c3e52154e8b1",
    "CMAKE_BUILD_TYPE": "Release",
    "CMAKE_MAKE_PROGRAM": str(WORK / "build-tools/bin/ninja"),
    "CMAKE_INSTALL_PREFIX": str(WORK / "opencv-install"),
    "CMAKE_OSX_DEPLOYMENT_TARGET": "11.0",
    "BUILD_LIST": "core,imgproc,python3",
    "BUILD_SHARED_LIBS": "OFF",
    "BUILD_TESTS": "OFF",
    "BUILD_PERF_TESTS": "OFF",
    "BUILD_EXAMPLES": "OFF",
    "BUILD_opencv_apps": "OFF",
    "BUILD_JAVA": "OFF",
    "BUILD_opencv_java": "OFF",
    "BUILD_opencv_python2": "OFF",
    "BUILD_opencv_python3": "ON",
    "OPENCV_PYTHON3_VERSION": "3.12",
    "PYTHON3_EXECUTABLE": str(WORK / "venv/bin/python"),
    "PYTHON3_INCLUDE_DIR": str(BASE / "include/python3.12"),
    "PYTHON3_LIBRARY": str(BASE / "lib/libpython3.12.dylib"),
    "PYTHON3_NUMPY_INCLUDE_DIRS": str(
        WORK / "venv/lib/python3.12/site-packages/numpy/_core/include"
    ),
    "PYTHON3_PACKAGES_PATH": str(WORK / "opencv-install/python"),
    "WITH_FFMPEG": "OFF",
    "WITH_GSTREAMER": "OFF",
    "WITH_AVFOUNDATION": "OFF",
    "WITH_V4L": "OFF",
    "WITH_OPENNI": "OFF",
    "WITH_OPENNI2": "OFF",
    "WITH_OBSENSOR": "OFF",
    "WITH_QT": "OFF",
    "WITH_GTK": "OFF",
    "WITH_COCOA": "OFF",
    "WITH_OPENGL": "OFF",
    "WITH_IPP": "OFF",
    "WITH_ITT": "OFF",
    "WITH_TBB": "OFF",
    "WITH_OPENMP": "OFF",
    "WITH_OPENCL": "OFF",
    "WITH_ADE": "OFF",
    "WITH_PROTOBUF": "OFF",
    "BUILD_PROTOBUF": "OFF",
    "WITH_JPEG": "OFF",
    "WITH_PNG": "OFF",
    "WITH_TIFF": "OFF",
    "WITH_WEBP": "OFF",
    "WITH_OPENEXR": "OFF",
    "WITH_JASPER": "OFF",
    "WITH_OPENJPEG": "OFF",
    "BUILD_ZLIB": "OFF",
    "OPENCV_GENERATE_PKGCONFIG": "OFF",
}
commands = [
    [
        str(CMAKE),
        "-S",
        str(SOURCE),
        "-B",
        str(BUILD),
        "-G",
        "Ninja",
        *[f"-D{k}={v}" for k, v in configuration.items()],
    ],
    [str(CMAKE), "--build", str(BUILD), "--target", "opencv_python3", "--parallel", "2"],
]
(HERE / "opencv-build-recipe.json").write_text(
    json.dumps(
        {"configuration": configuration, "commands": commands, "network_policy": POLICY}, indent=2
    )
    + "\n"
)
environment = dict(os.environ)
environment["CMAKE_BUILD_PARALLEL_LEVEL"] = "2"
for index, command in enumerate(commands):
    with (HERE / f"opencv-build-{index}.log").open("w") as log:
        subprocess.run(
            ["/usr/bin/sandbox-exec", "-p", POLICY, *command],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=True,
        )
print("Image-only OpenCV built successfully")
