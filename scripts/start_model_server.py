"""Start the pinned local model-only server using an existing local GGUF."""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TAG = "b11963"
SHA256 = "b11dd41563b07b250841b4742e1a6e9675b34f82c7c7486a65c958f795b99ea3"
DEFAULT_MODEL = Path.home() / ".lmstudio/models/Qwen/Qwen3-14B-GGUF/Qwen3-14B-Q4_K_M.gguf"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL,
                        help="Local licensed GGUF; defaults to the measured official Qwen3-14B Q4_K_M")
    parser.add_argument("--ctx-size", type=int, choices=(8192, 16384), default=16384,
                        help="Context window for the baseline local server; investigations use a 16K ceiling")
    args = parser.parse_args()
    if not args.model.is_file():
        parser.error("Supply --model with a local, licensed tool-capable GGUF model")
    try:
        response = httpx.get("http://127.0.0.1:1234/v1/models", timeout=2, trust_env=False)
        response.raise_for_status()
        print("A model server is already listening on port1234; leaving it running.")
        return
    except httpx.HTTPError:
        pass
    runtime = ROOT / ".visionapp/runtime"
    binary = runtime / f"llama-{TAG}" / "llama-server"
    if not binary.exists():
        runtime.mkdir(parents=True, exist_ok=True)
        archive = runtime / "llama.tar.gz"
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{TAG}/llama-{TAG}-bin-macos-arm64.tar.gz"
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with archive.open("wb") as stream:
                for chunk in response.iter_bytes():
                    stream.write(chunk)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise ValueError("Pinned server archive checksum mismatch")
        with tarfile.open(archive) as bundle:
            bundle.extractall(runtime, filter="data")
    log_path = ROOT / ".visionapp/planner.log"
    with log_path.open("a") as log:
        process = subprocess.Popen([str(binary), "-m", str(args.model), "--host", "127.0.0.1",
            "--port", "1234", "--alias", "visionapp-planner", "--ctx-size", str(args.ctx_size), "--parallel", "1",
            "--reasoning", "off", "--chat-template-kwargs", '{"enable_thinking":false}',
            "--no-webui", "-lv", "4"], stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    (ROOT / ".visionapp/planner.pid").write_text(str(process.pid))
    print(f"Model server starting (PID {process.pid}); log: {log_path}")


if __name__ == "__main__":
    main()
