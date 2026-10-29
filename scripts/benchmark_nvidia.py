"""Score published synthetic labels without creating human deployment approval."""
import json
import time
from pathlib import Path

from engine.eval import evaluate
from engine.service import WorkspaceService
from engine.store.repository import atomic_model


def main() -> None:
    data = Path.home() / "Library/Application Support/VisionApp"
    service = WorkspaceService(data)
    project = next(p for p in service.list_projects() if p.name == "NVIDIA warehouse · annotated synthetic")
    dataset = service.annotations(project.id).model_copy(deep=True)
    # This benchmark trusts published GT; these flags never enter the app project.
    for annotation in dataset.annotations:
        annotation.reviewed = True
    started = time.perf_counter()
    result = evaluate(project.candidates[0], dataset, service.root(project.id))
    destination = Path("artifacts/nvidia-benchmark")
    destination.mkdir(parents=True, exist_ok=True)
    atomic_model(destination / "metrics.json", result)
    provenance = json.loads((service.root(project.id) / "source-provenance.json").read_text())
    (destination / "provenance.json").write_text(json.dumps({
        "dataset": provenance["dataset"], "revision": provenance["revision"],
        "scene": provenance["scene"], "camera": provenance["camera"], "frames": provenance["frames"],
        "license": "CC-BY-4.0", "synthetic": True,
        "classes": ["person", "forklift"], "confidence_threshold": 0.15, "matching_iou": 0.5,
        "device": "Apple M4 Pro MPS", "elapsed_s": time.perf_counter() - started,
        "limitations": "One camera, correlated synthetic frames. Not pallet/damage/label accuracy. No deployment approval created.",
    }, indent=2))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
