"""Independent typed-decision response transports; never native tool execution."""
from pydantic import JsonValue, TypeAdapter

from spec.investigation import InvestigationTransport

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
FUNCTION_NAME = "submit_decision"


def generation_options(schema: dict[str, JsonValue], tokens: int,
                       transport: InvestigationTransport) -> dict[str, JsonValue]:
    options: dict[str, JsonValue] = {"temperature": 0, "max_tokens": tokens}
    if transport == "structured_json":
        options["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "InvestigationDecision", "strict": True, "schema": schema}}
    else:
        options.update(tools=[{"type": "function", "function": {
            "name": FUNCTION_NAME, "description": "Submit one typed investigation decision for host validation; this call executes no CV tools.",
            "strict": True, "parameters": schema}}],
            tool_choice={"type": "function", "function": {"name": FUNCTION_NAME}}, parallel_tool_calls=False)
    return options


def function_decision(response: dict[str, JsonValue]) -> dict[str, JsonValue]:
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("Decision function response requires exactly one completion choice")
    choice = choices[0]
    if choice.get("finish_reason") != "tool_calls":
        raise ValueError("Decision function response did not complete with finish_reason=tool_calls")
    message = choice.get("message")
    calls = message.get("tool_calls") if isinstance(message, dict) else None
    if not isinstance(calls, list) or len(calls) != 1:
        raise ValueError("Decision function response requires exactly one submit_decision call")
    call = calls[0]
    if not isinstance(call, dict) or call.get("type") != "function" or not isinstance(call.get("id"), str) or not call["id"]:
        raise ValueError("Decision function response contains an incomplete function call")
    function = call.get("function")
    if not isinstance(function, dict) or function.get("name") != FUNCTION_NAME:
        raise ValueError("Decision function response must call submit_decision")
    arguments = function.get("arguments")
    if not isinstance(arguments, str) or not arguments.strip():
        raise ValueError("Decision function response has no complete arguments")
    try:
        return JSON_OBJECT.validate_json(arguments)
    except ValueError as error:
        raise ValueError("Decision function arguments must be one complete JSON object") from error


def completion_failure(response: dict[str, JsonValue], transport: InvestigationTransport) -> str | None:
    """Reject incomplete responses without interpreting reasoning/prose as actions."""
    if "choices" not in response and transport == "structured_json":
        return None  # Internal scripted JSON deciders have no completion envelope.
    choices = response.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if isinstance(choice, dict) and choice.get("finish_reason") == "length":
        return "Model completion exhausted its total output allowance (finish_reason=length); no action executed"
    if transport == "decision_function":
        try:
            function_decision(response)
        except ValueError as error:
            return f"{error}; no action executed"
        return None
    message = choice.get("message") if isinstance(choice, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        return "Model completion returned no final content; no action executed"
    return None
