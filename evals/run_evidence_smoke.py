"""Explicit live planner+MCP+API probe on synthetic recorded events, not CV accuracy."""

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

import httpx
from PIL import Image
from pydantic import JsonValue

from engine.api.application import create_app
from engine.service import WorkspaceService
from engine.store.models import EventRecord, Settings


async def run(output: Path, model: str, url: str) -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="visionapp-evidence-live-"))
    service = WorkspaceService(data_dir)
    project = service.create_project("Synthetic evidence semantic smoke", "custom")
    project.synthetic, project.fixture = True, True
    project.data_origin = "Synthetic recorded observations for query testing; no detector executed"
    service.repository.save(project)
    service.repository.save_settings(Settings(model_url=url, planner_model=model))
    root = service.root(project.id)
    frame = root / "synthetic-frame.png"
    Image.new("RGB", (128, 96), "orange").save(frame)
    moment = datetime.now(UTC) - timedelta(milliseconds=100)
    with service.repository.connection() as connection:
        for index in range(1205):
            event = EventRecord(id=f"synthetic-damage-{index:04}", created_at=moment.isoformat(),
                image_path=str(frame), crop_path=str(frame), label="damaged pallet", confidence=.9,
                counts={"4": 99}, payload={"kind": "detection", "zone": "4", "synthetic": True, "run_id": "synthetic-recording"})
            connection.execute("INSERT INTO events VALUES (?,?,?,?)", (event.id, project.id, event.created_at, event.model_dump_json()))
    service.repository.add_event(project.id, EventRecord(id="synthetic-forklift", created_at=(moment - timedelta(days=1)).isoformat(),
        image_path=str(frame), crop_path=str(frame), label="forklift", confidence=.95,
        payload={"kind": "detection", "zone": "receiving east", "synthetic": True}))
    service.repository.add_event(project.id, EventRecord(id="synthetic-connector", created_at=(moment - timedelta(hours=2)).isoformat(),
        image_path=str(frame), crop_path=str(frame), label="bent connector", confidence=.88,
        payload={"kind": "detection", "zone": "inspection bench", "synthetic": True}))
    project_before = (root / "project.json").read_bytes()
    records_before = service.repository.connection().execute("SELECT COUNT(*) FROM events").fetchone()[0]
    app = create_app(data_dir)
    cases: list[tuple[str, int | None, dict[str, JsonValue]]] = [
        ("How many damaged pallets on dock 4 today?", 1205, {"labels": ["damaged pallet"], "zones": ["4"], "period": "today", "operation": "count"}),
        ("How many forklifts at receiving east yesterday?", 1, {"labels": ["forklift"], "zones": ["receiving east"], "period": "yesterday", "operation": "count"}),
        ("How many unique damaged pallets on dock 4 today?", None, {}),
        ("How many purple dragons on dock 4 today?", None, {}),
        ("Show bent connectors at inspection bench over the last 48 hours.", 1, {"labels": ["bent connector"], "zones": ["inspection bench"], "period": "last_hours", "amount": 48, "operation": "show"}),
        ("How many damaged pallets on dock 4?", None, {}),
    ]
    results = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=65) as client:
        for question, expected, interpretation in cases:
            started = monotonic()
            response = await client.post(f"/projects/{project.id}/ask", json={"question": question, "timezone": "UTC"})
            body = response.json()
            query_id = body.get("query_id")
            item = {"question": question, "expected_count": expected, "expected_interpretation": interpretation, "http_status": response.status_code,
                    "elapsed_s": round(monotonic() - started, 3), "response": body}
            if query_id:
                replay = await client.post(f"/projects/{project.id}/evidence-queries/{query_id}/replay")
                spans = await client.get(f"/projects/{project.id}/traces", params={"operation_id": query_id})
                item["replay"] = replay.json()
                item["trace_kinds"] = [span["kind"] for span in spans.json()]
            actual = (body.get("interpretation") or {}).get("matched_observations")
            executed = (body.get("interpretation") or {}).get("query") or {}
            flattened = {**executed, **executed.get("time", {})}
            correct_query = all(flattened.get(key) == value for key, value in interpretation.items())
            item["passed"] = response.status_code == 200 and correct_query and (actual == expected if expected is not None else bool(body.get("questions")))
            results.append(item)
    records_after = service.repository.connection().execute("SELECT COUNT(*) FROM events").fetchone()[0]
    report = {"mode": "live-local-semantic-evidence", "model": model, "data_dir": str(data_dir), "project_id": project.id,
              "provenance": project.data_origin, "cases": results,
              "no_project_mutation": project_before == (root / "project.json").read_bytes(),
              "no_duplicate_effects": records_before == records_after,
              "no_deployment": service.get_project(project.id).deployment_id is None}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"artifact": str(output), "cases": [{"question": case["question"], "passed": case["passed"],
        "elapsed_s": case["elapsed_s"], "status": case["http_status"]} for case in results]}, indent=2))
    if not all(item["passed"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="visionapp-planner")
    parser.add_argument("--url", default="http://127.0.0.1:1234/v1")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.output, arguments.model, arguments.url))
