"""A0 graph guidance must not enlarge or alter the shared planner contract."""
import json
from copy import deepcopy
from typing import Any

import pytest

import agent.investigation as investigation
from agent.investigation import (
    action_contracts,
    node_contracts,
    workflow_action_contracts,
    workflow_capabilities,
)
from agent.investigation_docs import graph_contract_schema
from engine.blocks.registry import REGISTRY
from spec.authoring import GraphCandidate
from spec.workflow_ports import WORKFLOW_INPUT_PORTS


def without_descriptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: without_descriptions(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def test_a0_documentation_keeps_shared_graph_schema_unchanged() -> None:
    shared = GraphCandidate.model_json_schema()
    before = deepcopy(shared)
    documented = graph_contract_schema()
    assert without_descriptions(documented) == shared
    assert GraphCandidate.model_json_schema() == before
    assert documented["description"] and "description" not in shared
    assert all(list(item["properties"])[0] == "type" for item in shared["$defs"].values())


def test_a0_visible_graph_docs_preserve_semantics_ports_and_constraints() -> None:
    nodes = node_contracts()
    assert all(node["description"] for node in nodes.values())
    assert "does not semantically select" in nodes["ocr"]["description"]
    assert "does not filter or replace" in nodes["match"]["description"]
    assert "never dispatch external events" in nodes["sink_event"]["description"]
    assert "no path or media ID" in nodes["frame_sample"]["description"]
    assert "never a media ID or filename" in nodes["ocr"]["fields"]["image"]["description"]
    assert "[left, top, right, bottom]" in nodes["crop"]["fields"]["box"]["description"]
    assert nodes["ocr"]["outputs"] == {"text": "text"}
    assert nodes["resize"]["fields"]["width"]["maximum"] == 8192
    graph = workflow_action_contracts()["construct_workflow"]["fields"]["graph"]
    assert "host binds source media separately" in graph["description"]
    assert "one to four detector/reader nodes" in graph["properties"]["nodes"]["description"]
    assert graph["properties"]["nodes"]["maxItems"] == 16


def test_investigating_inventory_matches_actual_graph_vocabulary_and_semantics() -> None:
    inventory = workflow_capabilities()
    nodes = node_contracts()
    schema = GraphCandidate.model_json_schema()
    variants = schema["properties"]["nodes"]["items"]["discriminator"]["mapping"]
    operators = {row["type"]: row for row in inventory["operators"]}
    assert set(operators) == set(variants) == set(nodes) == set(WORKFLOW_INPUT_PORTS)
    assert inventory["total_operators"] == inventory["returned_operators"] == len(variants)
    assert inventory["truncated"] is False
    for kind, row in operators.items():
        assert set(row) == {"type", "inputs", "outputs", "description"}
        assert row["inputs"] == WORKFLOW_INPUT_PORTS[kind] == REGISTRY[kind].inputs
        assert row["outputs"] == REGISTRY[kind].outputs == nodes[kind]["outputs"]
        assert row["description"] == nodes[kind]["description"]
    assert "not model availability or readiness" in inventory["scope"]
    assert "does not locate objects dynamically" in operators["crop"]["description"]
    assert "does not filter or replace" in operators["match"]["description"]


def test_inventory_and_preparation_docs_are_compact_and_not_task_specific() -> None:
    inventory = workflow_capabilities()
    text = json.dumps(inventory, ensure_ascii=False)
    assert len(text) <= inventory["context_char_limit"] == 3500
    assert not any(word in text for word in ("$defs", "properties", "model_capability_id", "fixture", "QZ-4817", "pallet"))
    actions = action_contracts()
    description = actions["prepare_workflow"]["description"]
    assert "subsequent typed workflow submission" in description
    assert "request itself creates no graph" in description
    assert "successful probes do not automatically" in description
    assert "crop and resize" in description
    assert len(json.dumps(actions, ensure_ascii=False)) < 6000
    assert investigation.prompt_transport_fits({"action_contracts": actions, "workflow_capabilities": inventory}, 1400)


def test_inventory_growth_has_explicit_counts_and_whole_operator_omissions(monkeypatch: pytest.MonkeyPatch) -> None:
    contracts = node_contracts()
    contracts["barcode"]["description"] = "Large future contract. " * 1000
    monkeypatch.setattr(investigation, "node_contracts", lambda: contracts)
    inventory = workflow_capabilities()
    assert len(json.dumps(inventory, ensure_ascii=False)) <= inventory["context_char_limit"]
    assert inventory["total_operators"] == len(contracts)
    assert inventory["returned_operators"] == len(inventory["operators"]) < len(contracts)
    assert inventory["truncated"] is True
    assert all(row["description"] == contracts[row["type"]]["description"] for row in inventory["operators"])
