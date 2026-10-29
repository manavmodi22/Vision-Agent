"""Investigation MCP transport; no engine or filesystem access."""
from __future__ import annotations

import json

from mcp import ClientSession
from pydantic import JsonValue, TypeAdapter

from agent.machine import AgentError
from spec.investigation import BuilderDecision, TaskState

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class InvestigationClient:
    def __init__(self, session: ClientSession, project_id: str, task_id: str) -> None:
        self.session = session
        self.project_id = project_id
        self.task_id = task_id

    async def call(self, name: str, arguments: dict[str, JsonValue] | None = None) -> dict[str, JsonValue]:
        result = await self.session.call_tool(name, {
            **(arguments or {}), "project_id": self.project_id, "task_id": self.task_id,
        })
        if result.isError:
            raise AgentError(" ".join(item.text for item in result.content if item.type == "text"))
        if result.structuredContent is not None:
            return JSON_OBJECT.validate_python(result.structuredContent)
        for item in result.content:
            if item.type == "text":
                return JSON_OBJECT.validate_python(json.loads(item.text))
        raise AgentError(f"{name} returned no structured observation")

    async def context(self) -> dict[str, JsonValue]:
        return await self.call("investigation_context_read")

    async def model_start(self, context: dict[str, JsonValue], model: str) -> str:
        value = await self.call("investigation_model_start", {"context": context, "model": model})
        call_id = value.get("id")
        if not isinstance(call_id, str):
            raise AgentError("Model capture did not return an ID")
        return call_id

    async def model_finish(self, call_id: str, response: dict[str, JsonValue] | None,
                           error: str | None = None) -> None:
        await self.call("investigation_model_finish", {"call_id": call_id, "response": response, "error": error})

    async def step(self, decision: BuilderDecision) -> dict[str, JsonValue]:
        return await self.call("investigation_step", {"decision": decision.model_dump(mode="json")})

    async def stop(self, reason: str) -> TaskState:
        return TaskState.model_validate(await self.call("investigation_stop", {"reason": reason}))
