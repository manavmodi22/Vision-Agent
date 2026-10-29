"""Reproduce isolated existing benchmarks with measured memory abort conditions."""
import argparse
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--label", required=True)
parser.add_argument("--model", required=True)
parser.add_argument("--kind", choices=["initial", "refinement"], required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
art = root / "artifacts/stronger-planner"
output = art / (args.label + ".json")
workspace = root / ".visionapp" / ("stronger-planner-" + args.label)
command = [str(root / ".venv/bin/python"), "-m"]
if args.kind == "initial":
    command += ["evals.run_custom_goals", "--workdir", str(workspace)]
    for case in ["count-capacity", "count-duration", "damage-both", "ocr-match"]:
        command += ["--case", case]
else:
    command += ["evals.run_refinement_live", "--workspace", str(workspace), "--ids",
                "remove_class,count_upper,sample_seconds,eval_recall,read_text_exact"]
command += ["--url", "http://127.0.0.1:1236/v1", "--model", args.model,
            "--output", str(output)]
env = dict(os.environ, VISION_APP_BINARY=str(root / "app/.build/debug/VisionApp"))
log = art / (args.label + ".log")
samples, seen, aborted = [], 0, None
started = time.monotonic()
with log.open("w") as stream:
    process = subprocess.Popen(command, cwd=root, stdout=stream,
        stderr=subprocess.STDOUT, env=env, start_new_session=True)
    while process.poll() is None:
        level = int(subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            capture_output=True, text=True, check=True).stdout.strip())
        stats = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True).stdout
        swapouts = int(re.search(r"Swapouts:\s+(\d+)", stats).group(1))
        samples.append({"elapsed_s": time.monotonic() - started,
                        "pressure_level": level, "swapouts_pages": swapouts})
        recent = [sample for sample in samples
                  if sample["elapsed_s"] >= samples[-1]["elapsed_s"] - 30]
        if level >= 4 or (swapouts - recent[0]["swapouts_pages"]) * 16384 > 1024 ** 3:
            aborted = "critical pressure or >1GiB swapout growth in30s"
            os.killpg(process.pid, signal.SIGTERM)
            print("ABORT", aborted, flush=True)
            break
        text = log.read_text()
        if text[seen:]:
            print(text[seen:], end="", flush=True)
        seen = len(text)
        time.sleep(3)
    process.wait()
print(log.read_text()[seen:], end="", flush=True)
(art / (args.label + "-resources.json")).write_text(json.dumps({
    "argv": command, "exit_code": process.returncode, "aborted": aborted,
    "samples": samples, "elapsed_s": time.monotonic() - started}, indent=2))
print("Probe ended", process.returncode, "samples", len(samples), flush=True)
raise SystemExit(process.returncode)
