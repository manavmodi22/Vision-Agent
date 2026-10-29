"""Model context must retain exact authority without silently changing readings."""
from copy import deepcopy

from mcp_server.investigation_projection import probe_projection, workflow_projection
from mcp_server.investigations import observation_projection
from spec.investigation import Observation


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


def test_compact_readings_beyond_fifth_are_visible_without_semantic_selection() -> None:
    items = [{"text": f"VALUE-{index}", "source_box": [.1, .2, .3, .4]} for index in range(14)]
    payload = {"executed": True, "items": items, "total_items": 14,
               "returned_items": 14, "truncated": False, "next_cursor": None}
    projected = probe_projection(payload)
    assert projected["items"] == items
    assert projected["returned_items"] == 14
    assert projected["truncated"] is False


def test_oversized_probe_value_is_omitted_honestly_with_exact_retrieval_action() -> None:
    payload = {"executed": True, "items": [{"text": "X" * 10000}, {"text": "SECOND"}],
               "total_items": 30, "returned_items": 2, "truncated": True,
               "next_cursor": "abcdef1234567890:20"}
    before = deepcopy(payload)
    observation = Observation(id="a" * 32, action_id="b" * 32, result_type="run_probe", status="completed",
                              payload=payload, created_at="2026-10-29T00:00:00Z")
    projected = observation_projection(observation)["payload"]
    assert projected["items"] == []
    assert projected["returned_items"] == 0 and projected["total_items"] == 30
    assert projected["truncated"] is True and projected["next_cursor"] is None
    assert projected["retrieve_saved_values"] == {"type": "inspect_observation", "observation_id": observation.id,
                                                "view": "values", "limit": 1, "cursor": None}
    assert payload == before
