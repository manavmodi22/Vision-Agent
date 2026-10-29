"""Model context must retain exact authority without silently changing readings."""
from copy import deepcopy

from mcp_server.investigation_projection import probe_projection, workflow_projection


def test_large_workflow_projection_preserves_authority_and_retrieval_without_mutation() -> None:
    payload = {
        "executed": True, "validated": True, "preview_success": True,
        "workflow_revision_id": "a" * 32, "spec_hash": "b" * 64, "preview_spec_hash": "b" * 64,
        "preview_media_ids": ["first", "second"],
        "preview": {"elapsed_s": 2.0, "warnings": [], "frames": [
            {"image_path": "/private/task/first.png", "source_image_sha256": "c" * 64,
             "texts": ["x" * 16000], "inferences": []},
            {"image_path": "/private/task/second.png", "texts": ["SECOND"], "inferences": []},
        ]},
        "artifact_refs": [{"path": "/private/task/preview.json"}],
    }
    before = deepcopy(payload)
    projected = workflow_projection(payload)
    assert payload == before
    assert projected["preview_media_ids"] == ["first", "second"]
    assert projected["spec_hash"] == projected["preview_spec_hash"] == "b" * 64
    assert projected["workflow_revision_id"] == "a" * 32
    assert "artifact_refs" not in projected
    assert projected["preview"]["frames"] == []
    assert projected["preview"]["frames_page"] == {
        "total_items": 2, "returned_items": 0, "truncated": True, "omitted_for_size": True,
    }
    assert "inspect_observation" in projected["projection_note"]


def test_probe_context_keeps_actual_values_and_source_boxes_without_repeated_geometry() -> None:
    payload = {"executed": True, "total_items": 1, "returned_items": 1, "truncated": False,
        "items": [{"text": "QZ-4817", "kind": "ocr", "item_id": "reading-1", "confidence": 1.0,
                   "box": [.1, .2, .3, .4], "source_box": [.10000001234, .2, .3, .4],
                   "polygon": [[.1, .2], [.3, .2], [.3, .4], [.1, .4]],
                   "source_polygon": [[.1, .2], [.3, .2], [.3, .4], [.1, .4]]}],
        "identity_refs": [{"identity_scope": "system_framework_versioned", "identity_hash": "a" * 64,
                           "artifact_hashes": {"verbose": "b" * 64}}],
        "artifact_refs": [{"sha256": "c" * 64}], "image_artifact": {"sha256": "c" * 64}}
    before = deepcopy(payload)
    projected = probe_projection(payload)
    assert projected["items"] == [{"text": "QZ-4817", "kind": "ocr", "item_id": "reading-1", "confidence": 1.0,
                                    "source_box": [.1, .2, .3, .4]}]
    assert projected["identity_refs"][0]["identity_scope"] == "system_framework_versioned"
    assert "artifact_refs" not in projected and "image_artifact" not in projected
    assert "rounded to six decimals" in projected["projection_note"]
    assert payload == before


def test_preview_projection_keeps_real_readings_geometry_and_marks_partial_lists() -> None:
    readings = [{"text": f"ITEM-{i}", "box": [0, 0, .5, .5]} for i in range(7)]
    payload = {"preview": {"elapsed_s": .2, "frames": [{
        "source_image_sha256": "f" * 64, "texts": [item["text"] for item in readings],
        "inferences": [{"block_id": "ocr", "input_to_frame": [.5, 0, .5, 1], "result": {
            "task": "ocr", "input_size": [400, 300], "readings": readings,
            "identity": {"identity_scope": "system_framework_versioned", "identity_hash": "e" * 64,
                         "artifact_hashes": {"verbose": "d" * 64}},
        }}],
    }]}}
    before = deepcopy(payload)
    projected = workflow_projection(payload)
    frame = projected["preview"]["frames"][0]
    inference = frame["inferences"][0]
    assert frame["source_image_sha256"] == "f" * 64
    assert inference["input_to_frame"] == [.5, 0, .5, 1]
    assert inference["result"]["readings"] == readings[:5]
    assert inference["result"]["readings_page"] == {"total_items": 7, "returned_items": 5, "truncated": True}
    assert inference["result"]["identity"] == {"identity_scope": "system_framework_versioned", "identity_hash": "e" * 64}
    assert payload == before
