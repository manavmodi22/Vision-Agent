"""Local transport contract tests with scripted HTTP/SDK responses; no inference."""
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai.types.chat import ChatCompletion
from pydantic import ValidationError
from test_investigation_loop import reply, workspace

from agent.investigation import investigate, run_steps, verify_prompt_budget
from engine.store.models import Settings
from spec.investigation import InvestigationTransport


@pytest.mark.parametrize("finish_reason,content", [
    ("length", "valid"), ("length", None), ("stop", None), ("stop", ""), ("stop", " \n"), ("empty", None),
])
async def test_incomplete_completion_is_captured_once_without_dispatch(
    tmp_path: Path, finish_reason: str, content: str | None,
) -> None:
    store, project, task, client = workspace(tmp_path)
    captured: dict[str, Any] = {}

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        decision = reply(request["context"], {"type": "inspect_media"})["decision"]
        final = json.dumps(decision) if content == "valid" else content
        captured.update({"decision": decision, "choices": [{"index": 0, "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": final, "reasoning_content": "Opaque test trace"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 1400, "total_tokens": 1600},
            "context_budget": {"output_tokens": 1400}})
        if finish_reason == "empty":
            captured["choices"] = []
        return captured

    result = await run_steps(client, decide, "scripted-transport-test")
    calls = store.model_calls(project, task)
    assert result.status == "inconclusive" and result.budget.model_calls == 1
    assert len(calls) == 1 and calls[0].status == "failed"
    expected = "exhausted its total output allowance" if finish_reason == "length" else "no final content"
    assert expected in calls[0].error and expected in result.stop_reason
    assert calls[0].response == captured
    assert not store.actions(project, task) and not store.observations(project, task)


async def test_template_preflight_preserves_all_explicit_prompt_options_and_records_hash() -> None:
    messages = [{"role": "user", "content": "Actual context"}]
    options = {"response_format": {"type": "json_schema", "json_schema": {"name": "Choice", "strict": True,
                "schema": {"type": "object", "properties": {"value": {"type": "string"}},
                           "required": ["value"], "additionalProperties": False}}},
               "reasoning_effort": "medium", "chat_template_kwargs": {"custom_style": "brief"},
               "temperature": 0, "max_tokens": 1400}
    expected_request = {"model": "chosen", "messages": messages, **options}
    prompt = "Rendered with explicit schema and reasoning options"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "chosen", "owned_by": "llamacpp", "meta": {"n_ctx": 8192}}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_alias": "chosen", "default_generation_settings": {"n_ctx": 8192}})
        if request.url.path == "/apply-template":
            assert json.loads(request.content) == expected_request
            return httpx.Response(200, json={"prompt": prompt})
        assert request.url.path == "/tokenize"
        assert json.loads(request.content)["content"] == prompt
        return httpx.Response(200, json={"tokens": [12] * 5000})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        budget = await verify_prompt_budget(client, "http://localhost/v1", "chosen", messages, 1400,
                                            request_options=options)
    assert budget["rendered_prompt_sha256"] == hashlib.sha256(prompt.encode()).hexdigest()
    assert budget["template_request_sha256"] == hashlib.sha256(json.dumps(
        expected_request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert budget["input_tokens"] == 5000 and budget["output_tokens"] == 1400
    assert budget["output_budget_scope"] == "total_generated_tokens_including_reasoning"
    assert budget["effective_context_tokens"] == 8192


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens", "n_predict"])
async def test_preflight_rejects_generation_limit_exceeding_reserved_allowance(field: str) -> None:
    def unused(request: httpx.Request) -> httpx.Response:
        pytest.fail("An inconsistent host request must fail before backend access")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unused)) as client:
        with pytest.raises(ValueError, match="reserved total output allowance"):
            await verify_prompt_budget(client, "http://localhost/v1", "chosen", [], 1400,
                                       request_options={field: 2600})


async def test_generic_backend_budget_counts_explicit_function_schema_and_options() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "generic", "owned_by": "local-server"}]})

    messages = [{"role": "user", "content": "Small context"}]
    options = {"tools": [{"type": "function", "function": {"name": "submit_decision",
                "parameters": {"type": "object", "description": "X" * 18000}}}],
               "tool_choice": {"type": "function", "function": {"name": "submit_decision"}},
               "parallel_tool_calls": False}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        small = await verify_prompt_budget(client, "http://localhost/v1", "generic", messages, 1400)
        assert small["explicit_request_option_bytes"] == 0
        with pytest.raises(ValueError, match="exceeds 8192 tokens"):
            await verify_prompt_budget(client, "http://localhost/v1", "generic", messages, 1400,
                                       request_options=options)
        options["tools"][0]["function"]["parameters"]["description"] = "Small schema"
        result = await verify_prompt_budget(client, "http://localhost/v1", "generic", messages, 1400,
                                             request_options=options)
    expected_bytes = len(json.dumps(options, ensure_ascii=False).encode())
    assert result["explicit_request_option_bytes"] == expected_bytes
    assert result["estimated_input_tokens"] == (len(b"Small context") + expected_bytes + 1) // 2
    assert result["context_verified"] is False and result["effective_context_tokens"] == 8192


@pytest.mark.parametrize("transport", ["structured_json", "decision_function"])
async def test_production_decider_uses_same_options_for_preflight_and_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: InvestigationTransport,
) -> None:
    import agent.investigation as module

    store, project, task, client = workspace(tmp_path)
    original_http_client = httpx.AsyncClient
    template_request: dict[str, Any] = {}
    generation_request: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "chosen", "owned_by": "llamacpp", "meta": {"n_ctx": 16384}}]})
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_alias": "chosen", "default_generation_settings": {"n_ctx": 16384}})
        if request.url.path == "/apply-template":
            template_request.update(json.loads(request.content))
            return httpx.Response(200, json={"prompt": "Actual rendered test prompt"})
        assert request.url.path == "/tokenize"
        return httpx.Response(200, json={"tokens": [12] * 1000})

    async def create(**kwargs: Any) -> ChatCompletion:
        generation_request.update({key: value for key, value in kwargs.items() if key != "extra_body"})
        generation_request.update(kwargs["extra_body"])
        context = json.loads(generation_request["messages"][1]["content"])
        decision = reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "Protocol ended"})["decision"]
        message = {"role": "assistant", "content": json.dumps(decision), "reasoning_content": "Opaque test trace"}
        if transport == "decision_function":
            message.update(content=None, tool_calls=[{"id": "submission-1", "type": "function", "function": {
                "name": "submit_decision", "arguments": json.dumps(decision)}}])
        return ChatCompletion.model_validate({"id": "scripted", "object": "chat.completion", "created": 1,
            "model": "chosen", "choices": [{"index": 0,
                "finish_reason": "tool_calls" if transport == "decision_function" else "stop", "message": message}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050}})

    @asynccontextmanager
    async def fake_model(**kwargs: Any) -> Any:
        assert kwargs["max_retries"] == 0 and kwargs["timeout"].read == 150
        yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    @asynccontextmanager
    async def fake_tools(*args: Any) -> Any:
        yield SimpleNamespace(session=client.session)

    async def check_model(*args: Any) -> None:
        pass

    monkeypatch.setattr(module, "check_model", check_model)
    monkeypatch.setattr(module, "connect_tools", fake_tools)
    monkeypatch.setattr(module, "AsyncOpenAI", fake_model)
    monkeypatch.setattr(module, "DefaultAsyncHttpxClient", lambda **kwargs: None)
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original_http_client(
        transport=httpx.MockTransport(handle), **kwargs))
    result = await investigate(str(tmp_path / "workspace"), project, task, "http://127.0.0.1:1234/v1", "chosen",
                               transport=transport)
    assert result.status == "inconclusive" and result.budget.model_calls == 1
    assert template_request == generation_request
    assert generation_request["max_tokens"] == 1400 and generation_request["temperature"] == 0
    call = store.model_calls(project, task)[0]
    assert call.context["transport"] == transport
    if transport == "structured_json":
        assert generation_request["response_format"]["type"] == "json_schema"
        assert "tools" not in generation_request and "tool_choice" not in generation_request
    else:
        assert "response_format" not in generation_request
        assert generation_request["tool_choice"] == {"type": "function", "function": {"name": "submit_decision"}}
        assert generation_request["parallel_tool_calls"] is False
        assert len(generation_request["tools"]) == 1
        function = generation_request["tools"][0]["function"]
        assert function["name"] == "submit_decision" and function["parameters"] == call.context["schema"]
        assert "independent decision submission" in call.context["system"]
    response = call.response
    assert response["choices"][0]["message"]["reasoning_content"] == "Opaque test trace"
    assert response["usage"]["completion_tokens"] == 50
    assert response["context_budget"]["rendered_prompt_sha256"] == hashlib.sha256(b"Actual rendered test prompt").hexdigest()


def function_response(decision: dict[str, Any]) -> dict[str, Any]:
    return {"decision": decision, "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "reasoning_content": "Opaque test trace",
        "tool_calls": [{"id": "submission-1", "type": "function", "function": {
            "name": "submit_decision", "arguments": json.dumps(decision)}}]}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "total_tokens": 1050}}


@pytest.mark.parametrize("defect", ["wrong_name", "multiple", "missing_args", "empty_args", "invalid_args",
                                   "array_args", "length", "missing_calls", "incomplete", "missing_id"])
async def test_invalid_function_response_is_retained_without_dispatch_or_prose_fallback(tmp_path: Path, defect: str) -> None:
    store, project, task, client = workspace(tmp_path)
    response: dict[str, Any] = {}

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        decision = reply(request["context"], {"type": "inspect_media"})["decision"]
        response.update(function_response(decision))
        choice = response["choices"][0]
        message = choice["message"]
        message["content"] = json.dumps(decision)  # A valid prose fallback must not authorize execution.
        call = message["tool_calls"][0]
        if defect == "wrong_name":
            call["function"]["name"] = "inspect_media"
        elif defect == "multiple":
            message["tool_calls"].append({**call, "id": "submission-2"})
        elif defect == "missing_args":
            del call["function"]["arguments"]
        elif defect in {"empty_args", "invalid_args", "array_args"}:
            call["function"]["arguments"] = {"empty_args": "", "invalid_args": "{", "array_args": "[]"}[defect]
        elif defect == "length":
            choice["finish_reason"] = "length"
        elif defect == "missing_calls":
            message["tool_calls"] = []
        elif defect == "incomplete":
            choice["finish_reason"] = None
        else:
            del call["id"]
        return response

    result = await run_steps(client, decide, "scripted-model", transport="decision_function")
    calls = store.model_calls(project, task)
    assert result.status == "inconclusive" and result.budget.model_calls == 1
    assert len(calls) == 1 and calls[0].status == "failed" and calls[0].response == response
    assert "no action executed" in calls[0].error
    assert not store.actions(project, task) and not store.observations(project, task)


@pytest.mark.parametrize("defect", ["state_revision", "unknown_observation"])
async def test_function_arguments_still_require_current_revision_and_exposed_host_ids(tmp_path: Path, defect: str) -> None:
    store, project, task, client = workspace(tmp_path)
    attempts = 0

    async def decide(request: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        context = request["context"]
        assert request["transport"] == "decision_function"
        if attempts == 1:
            return function_response(reply(context, {"type": "inspect_media"})["decision"])
        identifier = context["observations"][-1]["id"]
        decision = reply(context, {"type": "finish", "outcome": "inconclusive", "summary": "Protocol ended",
                                   "evidence_ids": [identifier]}, [identifier])["decision"]
        assert request["schema"]["properties"]["based_on_observation_ids"]["items"]["enum"] == [identifier]
        if attempts == 2:
            if defect == "state_revision":
                decision["state_revision"] += 1
            else:
                decision["based_on_observation_ids"] = ["f" * 32]
        else:
            assert len(store.actions(project, task)) == 1
            assert "Invalid next-action response" in context["last_model_error"]
        return function_response(decision)

    result = await run_steps(client, decide, "scripted-model", transport="decision_function")
    assert result.status == "inconclusive" and result.budget.model_calls == 3
    assert len(store.actions(project, task)) == 2
    assert store.model_calls(project, task)[1].status == "failed"


def test_old_settings_keep_structured_json_default_without_model_routing() -> None:
    for name in ("", "arbitrary-model", "gpt-oss-20b"):
        assert Settings.model_validate({"planner_model": name}).investigation_transport == "structured_json"
    selected = Settings(investigation_transport="decision_function")
    assert Settings.model_validate_json(selected.model_dump_json()).investigation_transport == "decision_function"
    with pytest.raises(ValidationError):
        Settings.model_validate({"investigation_transport": "automatic"})
