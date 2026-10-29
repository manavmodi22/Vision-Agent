"""Run one unchanged full benchmark with source/model and resource evidence."""
import argparse
import datetime
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.runtime_identity import source_identity  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--phase", choices=["initial", "refinement"], required=True)
parser.add_argument("--expected-hash", required=True)
parser.add_argument("--ids", default="")
parser.add_argument("--case", action="append", default=[])
parser.add_argument("--cases-file", type=Path)
parser.add_argument("--label")
parser.add_argument("--clear-prompt-cache", action="store_true")
args = parser.parse_args()
art = ROOT / "artifacts/stronger-planner"
driver = "evals.run_custom_goals" if args.phase == "initial" else "evals.run_refinement_live"
case_file = "evals/custom_goals.json" if args.phase == "initial" else "evals/refinement_cases.json"
if args.cases_file:
    assert args.phase == "initial", "Alternate case files are for the initial-reading driver"
    case_file = args.cases_file.as_posix()
case_ids = [item["id"] for item in json.loads((ROOT / case_file).read_text())]
selected = args.ids.split(",") if args.ids else args.case or case_ids
assert set(selected) <= set(case_ids), "Unknown case selection"
assert not (args.ids and args.case), "Use only one case selection syntax"
assert not args.ids or args.phase == "refinement"
assert not args.case or args.phase == "initial"
case_count = len(selected)
label = args.label or "qwen14-final-" + args.phase + str(case_count)
assert re.fullmatch(r"[a-z0-9-]+", label), "Invalid artifact label"
assert not any((art / (label + suffix)).exists()
               for suffix in [".json", ".log", "-evidence.json"]), "Retain prior evidence; use a new label"
workspace_flag = "--workdir" if args.phase == "initial" else "--workspace"
command = [str(ROOT / ".venv/bin/python"), "-m", driver, workspace_flag,
           str(ROOT / ".visionapp" / label), "--output", str(art / (label + ".json")),
           "--model", "visionapp-planner", "--url", "http://127.0.0.1:1234/v1"]
if args.ids:
    command += ["--ids", args.ids]
for case in args.case:
    command += ["--case", case]
if args.cases_file:
    command += ["--cases-file", str((ROOT / args.cases_file).resolve())]


def identity() -> dict:
    pid = int((ROOT / ".visionapp/planner.pid").read_text())
    server = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                            capture_output=True, text=True, check=True).stdout.strip()
    models = httpx.get("http://127.0.0.1:1234/v1/models", timeout=3, trust_env=False).json()
    assert "Qwen3-14B-Q4_K_M.gguf" in server and "--port 1234" in server
    assert models["data"][0]["id"] == "visionapp-planner"
    return {"source_identity": source_identity(ROOT), "server_pid": pid,
            "server_command": server, "models_response": models,
            "at": datetime.datetime.now(datetime.UTC).isoformat()}


before = identity()
assert before["source_identity"] == args.expected_hash, before["source_identity"]
report = {"before": before, "argv": command, "planned_cases": case_count,
          "selected_cases": selected, "targeted": bool(args.ids or args.case or args.cases_file),
          "model_provenance": json.loads((art / "model-provenance.json").read_text()),
          "file_hashes": {name: hashlib.file_digest((ROOT / name).open("rb"), "sha256").hexdigest()
                         for name in [case_file, driver.replace(".", "/") + ".py"]}}
if args.clear_prompt_cache:
    slots = httpx.get("http://127.0.0.1:1234/slots", timeout=3, trust_env=False).json()
    assert all(not slot["is_processing"] for slot in slots), "Model is busy"
    response = httpx.post("http://127.0.0.1:1234/slots/0?action=erase", json={},
                          timeout=5, trust_env=False)
    response.raise_for_status()
    report["prompt_cache_erase"] = response.json()
    report["prompt_cache_erase_documentation"] = (
        "https://raw.githubusercontent.com/ggml-org/llama.cpp/b11963/tools/server/README.md")
(art / (label + "-evidence.json")).write_text(json.dumps(report, indent=2))
env = dict(os.environ, VISION_APP_BINARY=str(ROOT / "app/.build/debug/VisionApp"))
log = art / (label + ".log")
samples, seen, aborted = [], 0, None
started = time.monotonic()
with log.open("w") as stream:
    process = subprocess.Popen(command, cwd=ROOT, stdout=stream,
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
after = identity()
report.update(after=after, exit_code=process.returncode, aborted=aborted,
              samples=samples, elapsed_s=time.monotonic() - started,
              unchanged_source=before["source_identity"] == after["source_identity"],
              unchanged_server=before["server_command"] == after["server_command"])
(art / (label + "-evidence.json")).write_text(json.dumps(report, indent=2))
print("Full probe ended", process.returncode, "source unchanged", report["unchanged_source"], flush=True)
raise SystemExit(process.returncode)
