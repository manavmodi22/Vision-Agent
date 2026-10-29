"""Sample-source mapping tests use tiny generated transport fixtures only."""
import json
from pathlib import Path

import pytest
from PIL import Image

from engine.evidence_metadata import pixel_hash, pixel_hash_image, source_record


def sample_project(root: Path, *, explicit_mapping: bool) -> tuple[Path, Path]:
    media = root / "media"
    media.mkdir()
    original, later = media / "sample-frame.png", media / "later-import.png"
    Image.new("RGB", (8, 6), "red").save(original)
    Image.new("RGB", (8, 6), "blue").save(later)
    (root / "project.json").write_text(json.dumps({"media": [str(original), str(later)]}))
    (media / "media-sources.json").write_text(json.dumps({
        original.name: {"source_sha256": "a" * 64},
        later.name: {"source_sha256": "b" * 64},
    }))
    record = {
        "sample_id": "nvidia-warehouse-real", "sha256": "c" * 64,
        "video": "test/Warehouse_026/videos/Camera_0000.mp4", "synthetic": False,
        "frame_count": 1, "source_timestamps_s": [33.0],
    }
    if explicit_mapping:
        record["frames"] = [{"image_path": "media/sample-frame.png", "timestamp_s": 33.0}]
    (root / "sample-source.json").write_text(json.dumps(record))
    return original, later


@pytest.mark.parametrize("explicit_mapping", [False, True])
def test_sample_frame_keeps_original_video_identity(tmp_path: Path, explicit_mapping: bool) -> None:
    original, later = sample_project(tmp_path, explicit_mapping=explicit_mapping)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    record = source_record(tmp_path, str(original))
    assert record["source_sha256"] == "c" * 64
    assert record["timestamp_s"] == "33.0"
    assert record["data_origin"] == "real"
    assert "frame_index" not in record  # Requested timestamps do not prove an exact frame index.
    assert source_record(tmp_path, str(later)) == {"source_sha256": "b" * 64}
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}


def test_explicit_mapping_survives_project_order_change(tmp_path: Path) -> None:
    original, later = sample_project(tmp_path, explicit_mapping=True)
    (tmp_path / "project.json").write_text(json.dumps({"media": [str(later), str(original)]}))
    assert source_record(tmp_path, str(original))["source_sha256"] == "c" * 64
    assert source_record(tmp_path, str(later))["source_sha256"] == "b" * 64


def test_incomplete_legacy_mapping_is_rejected(tmp_path: Path) -> None:
    original, _ = sample_project(tmp_path, explicit_mapping=False)
    provenance = tmp_path / "sample-source.json"
    value = json.loads(provenance.read_text())
    value["frame_count"] = 20
    provenance.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="mapping is incomplete"):
        source_record(tmp_path, str(original))


def test_ephemeral_and_imported_pixel_identity_match_without_mutating_image(tmp_path: Path) -> None:
    image = Image.new("RGB", (8, 6), "red")
    image.putpixel((0, 0), (0, 0, 255))
    image.getexif()[274] = 6
    before = (image.size, image.tobytes(), dict(image.getexif()))
    path = tmp_path / "oriented.png"
    image.save(path, exif=image.getexif())
    assert pixel_hash_image(image) == pixel_hash(path)
    assert before == (image.size, image.tobytes(), dict(image.getexif()))
