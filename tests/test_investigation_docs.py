"""A0 graph guidance must not enlarge or alter the shared planner contract."""
from copy import deepcopy
from typing import Any

from agent.investigation import node_contracts, workflow_action_contracts
from agent.investigation_docs import graph_contract_schema
from spec.authoring import GraphCandidate


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
