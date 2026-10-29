"""Wire-level native metadata protocol and app lifecycle cleanup."""
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from agent.templates import build_template
from engine.api import create_app
from engine.live.contracts import CAPACITY_BYTES


def test_live_routes_preview_body_ordering_and_shutdown(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    service = app.state.service
    project = service.create_project("Native capture API test", "pallets")
    service.demo(project.id)
    service.save_candidates(project.id, build_template("pallets", "media", "fixture-color-v1"), "Count fixtures")
    with TestClient(app) as client:
        base = f"/projects/{project.id}/live"
        rejected = client.post(base, json={"source_kind": "camera", "source_label": "test"})
        assert rejected.status_code == 409
        response = client.post(base, json={"source_kind": "camera", "source_label": "test", "preview_only": True})
        assert response.status_code == 200
        session = response.json()
        path = Path(session["shared_memory_path"])
        assert session["capacity_bytes"] == CAPACITY_BYTES and session["sample_fps"] == 2
        with Image.open(service.get_project(project.id).media[1]) as image:
            frame = image.convert("RGBA")
        with path.open("r+b") as stream:
            stream.write(frame.tobytes("raw", "BGRA"))
        endpoint = base + "/" + session["session_id"]
        metadata = {"sequence": 1, "width": frame.width, "height": frame.height,
                    "bytes_per_row": frame.width * 4, "timestamp_s": 0}
        result = client.post(endpoint + "/frames", json=metadata)
        assert result.status_code == 200 and result.json()["result"]["counts"]["B"] == 3
        assert client.get(endpoint).json()["processed_frames"] == 1
        assert client.post(endpoint + "/frames", json={**metadata, "height": 0}).status_code == 422
        assert client.post(endpoint + "/stop").json()["state"] == "stopped"
        assert client.post(endpoint + "/frames", json=metadata).status_code == 410
        second = client.post(base, json={"source_kind": "screen_capture", "source_label": "window", "preview_only": True}).json()
        second_path = Path(second["shared_memory_path"])
        assert second_path.exists()
    assert not second_path.exists() and not service.events(project.id)
