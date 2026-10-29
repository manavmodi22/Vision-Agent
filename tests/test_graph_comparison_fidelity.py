"""Other inference branches must not hide dropped or changed text comparisons."""
from typing import Any

import pytest

from agent.graph_intent import validate_graph_intent
from spec.authoring import GraphCandidate


def candidate(*, comparison: bool = True, mode: str = "exact", emit: str = "all", events: bool = False,
              barcode: bool = False) -> GraphCandidate:
    nodes: list[dict[str, Any]] = [
        {"id": "sample", "type": "frame_sample", "fps": 2},
        {"id": "det", "type": "detect", "image": "$sample.frame", "classes": ["pallet"],
         "min_confidence": .4, "model_capability_id": "model.fixture-color-v1", "model_reason": "Software test"},
        {"id": "read", "type": "ocr", "image": "$sample.frame", "model_capability_id": "model.apple-vision", "model_reason": "Software test"},
    ]
    if barcode:
        nodes.append({"id": "codes", "type": "barcode", "image": "$sample.frame",
                      "model_capability_id": "model.apple-vision", "model_reason": "Software test"})
    if comparison:
        nodes.append({"id": "check", "type": "match", "text": "$read.text", "expected": "ABC-990", "mode": mode, "emit": emit})
    if events:
        nodes.append({"id": "record", "type": "sink_event", "event": "$check.event"})
    return GraphCandidate.model_validate({"name": "Mixed comparison", "nodes": nodes, "metric": "recall", "target": .9})


def test_detector_does_not_allow_omitting_reader_comparison() -> None:
    request = 'Detect pallets and read printed text. Compare against "ABC-990" exactly. Do not create events.'
    with pytest.raises(ValueError, match="comparison|expected"):
        validate_graph_intent([candidate(comparison=False)], request, {})
    validate_graph_intent([candidate()], request, {})


@pytest.mark.parametrize(("mode", "emit"), [("contains", "mismatched"), ("exact", "all")])
def test_detector_does_not_allow_changed_reader_event_semantics(mode: str, emit: str) -> None:
    request = 'Detect pallets and read printed text. Record events when text mismatches "ABC-990" exactly.'
    with pytest.raises(ValueError, match="match_mode|match_emit"):
        validate_graph_intent([candidate(mode=mode, emit=emit, events=True)], request, {})
    validate_graph_intent([candidate(emit="mismatched", events=True)], request, {})


def test_comparison_uses_explicit_reader_branch_when_another_reader_exists() -> None:
    request = ('Detect pallets. Read printed text and compare against "ABC-990" exactly. '
               'Read barcodes without a comparison. Do not record events.')
    validate_graph_intent([candidate(barcode=True)], request, {})
    with pytest.raises(ValueError, match="comparison|expected"):
        validate_graph_intent([candidate(comparison=False, barcode=True)], request, {})


def test_multiple_readers_cannot_choose_unspecified_comparison_owner() -> None:
    request = 'Detect pallets. Read printed text and barcodes. Compare against "ABC-990" exactly. Do not create events.'
    with pytest.raises(ValueError, match="reader|branch|comparison"):
        validate_graph_intent([candidate(barcode=True)], request, {})


def test_missing_literal_cannot_disappear_in_mixed_graph() -> None:
    request = 'Detect pallets and read printed text. Compare against the expected SKU.'
    with pytest.raises(ValueError, match="explicit expected|literal|comparison"):
        validate_graph_intent([candidate(comparison=False)], request, {})


@pytest.mark.parametrize("operation", ["tracking", "segmentation", "line-crossing", "VLM"])
def test_unsupported_composition_step_cannot_disappear(operation: str) -> None:
    with pytest.raises(ValueError, match="not supported"):
        validate_graph_intent([candidate(comparison=False)], f"Detect pallets and read printed text. Add {operation}.", {})


def test_negated_reading_task_is_not_required() -> None:
    validate_graph_intent([candidate(comparison=False)],
        "Detect pallets and read printed text. Do not read barcodes. Do not record events.", {})


def test_no_image_crop_is_distinct_from_no_saved_evidence_crops() -> None:
    validate_graph_intent([candidate(comparison=False)],
        "Detect pallets and read printed text. Do not crop or resize. Do not record events.", {})
    with pytest.raises(ValueError, match="retain local evidence"):
        validate_graph_intent([candidate(comparison=False)],
            "Detect pallets and read printed text. Do not save crops.", {})
