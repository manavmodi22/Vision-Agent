"""Bounded, OS-sandboxed runner. Child input contains no expected answers."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENV_ROOT = ROOT / ".visionapp/adapter-probes/ocr-minimal"
POLICY = "(version 1)(allow default)(deny network*)"


def denied_network():
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=1):
            pass
    except OSError as exc:
        if exc.errno != 1:
            raise RuntimeError(f"Network denial not established: {exc}") from exc
        return {"connection_blocked": True, "errno": exc.errno, "message": str(exc)}
    raise RuntimeError("Offline execution required, but network connection succeeded")


def loaded_libraries():
    library = ctypes.CDLL(None)
    count = library._dyld_image_count
    count.restype = ctypes.c_uint32
    name = library._dyld_get_image_name
    name.restype = ctypes.c_char_p
    name.argtypes = [ctypes.c_uint32]
    return sorted({name(i).decode() for i in range(count())})


def child(output, input_manifest):
    first_denial = denied_network()
    source_identity = {
        name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        for name in ("direct_ocr.py", "image_ops.py", "run_offline.py")
    }
    started = time.perf_counter()
    from direct_ocr import DirectOCR
    from paddle import is_compiled_with_cuda

    imported = time.perf_counter()
    engine = DirectOCR()
    initialized = time.perf_counter()
    rows = []
    inputs = json.loads(input_manifest.read_text())
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 500:
        raise ValueError("Expected 1–500 image rows")
    for row in inputs:
        if set(row) != {"id", "path", "sha256"}:
            raise ValueError("Only identity/path/hash may be passed into inference")
        if hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Fixture identity changed")
        result = engine.read(row["path"])
        rows.append({**row, **result})
        print(json.dumps({"id": row["id"], "observations": result["observations"]}), flush=True)
    packages = {item.metadata["Name"]: item.version for item in importlib.metadata.distributions()}
    disallowed = ["paddlex", "paddleocr", "shapely", "pypdfium2", "bidi", "bce"]
    imported_disallowed = [name for name in sys.modules if name.split(".")[0] in disallowed]
    if imported_disallowed:
        raise RuntimeError(f"Unexpected orchestration import: {imported_disallowed}")
    if any(
        hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest
        for name, digest in source_identity.items()
    ):
        raise RuntimeError("Prototype source changed during inference")
    report = {
        "status": "completed_actual_direct_cpu_inference",
        "production_registered": False,
        "representative_accuracy": None,
        "model_id": "ppocr-v5-mobile-en",
        "adapter_id": "paddle-ocr-cpu",
        "cuda_compiled": is_compiled_with_cuda(),
        "host": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "architecture": platform.machine(),
        },
        "policy": POLICY,
        "network_checks": [first_denial, denied_network()],
        "import_ms": (imported - started) * 1000,
        "initialize_ms": (initialized - imported) * 1000,
        "execution_ms": (time.perf_counter() - started) * 1000,
        "packages": packages,
        "prohibited_imports": imported_disallowed,
        "results": rows,
        "loaded_native_libraries": loaded_libraries(),
        "source_identity": source_identity,
        "limits": {
            "wall_clock_seconds": 180,
            "cpu_threads": 2,
            "max_input_pixels": 24000000,
            "max_input_side": 8192,
            "max_text_regions": 128,
            "recognition_batch": 1,
        },
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


def launch(output, paths=None):
    if paths is None:
        original = json.loads((ROOT / "artifacts/adapter-probes/ocr/cpu-inputs.json").read_text())
        clean_inputs = [{key: row[key] for key in ("id", "path", "sha256")} for row in original]
    else:
        path_list = json.loads(paths.read_text())
        if (
            not isinstance(path_list, list)
            or not 1 <= len(path_list) <= 500
            or not all(isinstance(p, str) for p in path_list)
        ):
            raise ValueError("--paths must be JSON array of 1–500 image path strings")
        clean_inputs = [
            {
                "id": str(i),
                "path": str(Path(p).resolve()),
                "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
            }
            for i, p in enumerate(path_list)
        ]
    input_manifest = output.with_name(output.stem + "-inputs.json")
    input_manifest.write_text(json.dumps(clean_inputs, indent=2) + "\n")
    environment = dict(os.environ)
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        environment[name] = "2"
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": "",
            "HF_HUB_OFFLINE": "1",
            "PYTHONNOUSERSITE": "1",
            "PADDLE_HOME": str(ENV_ROOT / "cache"),
            "XDG_CACHE_HOME": str(ENV_ROOT / "cache"),
        }
    )
    command = [
        "/usr/bin/sandbox-exec",
        "-p",
        POLICY,
        str(ENV_ROOT / "venv/bin/python"),
        str(Path(__file__).resolve()),
        "--child",
        "--output",
        str(output),
        "--input-manifest",
        str(input_manifest),
    ]
    with output.with_suffix(".log").open("w") as log:
        completed = subprocess.run(
            command, env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180
        )
    if completed.returncode:
        raise RuntimeError(
            f"Offline inference failed with exit {completed.returncode}; inspect log"
        )
    print(json.dumps({"output": str(output), "exit_code": completed.returncode}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument(
        "--paths", type=Path, help="JSON array of image paths; no expected transcripts"
    )
    parser.add_argument("--input-manifest", type=Path)
    parser.add_argument("--output", type=Path, default=HERE / "direct-result.json")
    args = parser.parse_args()
    child(args.output, args.input_manifest) if args.child else launch(args.output, args.paths)
