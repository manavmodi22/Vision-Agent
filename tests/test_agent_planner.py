import pytest
from pydantic import ValidationError

from agent.contracts import PlanResult
from agent.planner import PlannerError, local_model_url, plan
from agent.templates import build_template


@pytest.mark.parametrize("url", ["https://example.com/v1", "file:///tmp/model", "http://localhost.evil/v1", "http://user:password@localhost/v1"])
def test_planner_cannot_send_brief_to_remote_or_embedded_credentials(url: str) -> None:
    with pytest.raises(PlannerError):
        local_model_url(url)


@pytest.mark.parametrize("url", ["http://localhost:1234/v1", "http://127.0.0.1:8080/v1", "http://[::1]:1234/v1"])
def test_loopback_servers_are_replaceable(url: str) -> None:
    assert local_model_url(url + "/") == url


def test_typed_output_rejects_unbounded_questions_and_empty_plan() -> None:
    with pytest.raises(ValidationError):
        PlanResult(message="thinking")
    with pytest.raises(ValidationError):
        PlanResult(message="questions", questions=["one", "two", "three", "four"])
    with pytest.raises(ValidationError):
        PlanResult(message="question", questions=[""])


async def test_missing_model_is_an_error_not_an_offline_template() -> None:
    with pytest.raises(PlannerError, match="Choose a planner model"):
        await plan("Count pallets", "media", {"mcp_data_dir": "/tmp/vision-test", "project_id": "test"})


@pytest.mark.parametrize("use_case,metric,block", [
    ("pallets", "count_mae", "zone_filter"),
    ("damage", "recall", "detect"),
    ("labels", "text_accuracy", "ocr"),
])
def test_authored_templates_use_declared_pipeline_contract(use_case: str, metric: str, block: str) -> None:
    candidates = build_template(use_case, "media", "fixture-color-v1")
    assert len(candidates) == 1
    spec = candidates[0]
    assert spec.eval.metric == metric
    assert block in {item.type for item in spec.blocks}
    assert spec.blocks[0].inputs["frames"] == "$inputs.source"
    assert spec.inputs["source"].type == "image_folder"


def test_template_source_type_and_unknown_use_case() -> None:
    assert build_template("pallets", "sample.mov", "fixture-color-v1")[0].inputs["source"].type == "video_file"
    assert build_template("labels", "label.png", "fixture-color-v1")[0].inputs["source"].type == "image_file"
    with pytest.raises(ValueError, match="Unknown use case"):
        build_template("inventory forecasting", "media", "fixture-color-v1")
