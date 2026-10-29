import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from engine.api.sample_routes import REVISION, SAMPLE_ID, VIDEO, catalog, import_sample
from engine.service import WorkspaceService


def test_public_sample_is_unreviewed_owned_and_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = WorkspaceService(tmp_path)
    root = tmp_path / "datasets/nvidia-smartspaces"
    video = root / VIDEO
    video.parent.mkdir(parents=True)
    video.write_bytes(b"isolated sample transport fixture")
    (root / "manifest.json").write_text(json.dumps({
        "revision": REVISION, "license": "CC-BY-4.0",
        "files": [{"path": VIDEO, "sha256": hashlib.sha256(video.read_bytes()).hexdigest()}],
    }))

    def extract(path: Path, destination: Path) -> list[str]:
        assert path == video
        values = []
        for index in range(20):
            target = destination / f"frame-{index}.png"
            Image.new("RGB", (30, 20), (index, 0, 0)).save(target)
            values.append(str(target))
        return values

    monkeypatch.setattr("engine.api.sample_routes.extract_sample", extract)
    project = service.create_project("Sample build", "custom")
    assert catalog(service)[0].available
    imported = import_sample(service, project.id, SAMPLE_ID)
    assert len(imported.media) == 20
    assert all(Path(path).is_file() for path in imported.media)
    assert all(not row.reviewed and not row.detections for row in service.annotations(project.id).annotations)
    assert len(import_sample(service, project.id, SAMPLE_ID).media) == 20
    provenance = json.loads((service.root(project.id) / "sample-source.json").read_text())
    assert provenance["source_timestamps_s"] == [33 + index * 0.75 for index in range(20)]
    assert provenance["license"] == "CC-BY-4.0"
    assert imported.deployment_id is None


def test_missing_and_tampered_sample_never_imports(tmp_path: Path) -> None:
    service = WorkspaceService(tmp_path)
    project = service.create_project("Missing sample", "custom")
    assert not catalog(service)[0].available
    with pytest.raises(ValueError, match="not installed"):
        import_sample(service, project.id, SAMPLE_ID)
    root = tmp_path / "datasets/nvidia-smartspaces"
    path = root / VIDEO
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed")
    (root / "manifest.json").write_text(json.dumps({
        "revision": REVISION, "license": "CC-BY-4.0", "files": [{"path": VIDEO, "sha256": "0" * 64}],
    }))
    with pytest.raises(ValueError, match="bytes differ"):
        import_sample(service, project.id, SAMPLE_ID)
    assert service.get_project(project.id).media == []
