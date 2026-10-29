"""Capture each actual Pydantic AI model request, including validation retries."""

import asyncio

from pydantic import JsonValue, TypeAdapter
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from agent.contracts import PlanDecision
from agent.mcp_client import MCPTools

JSON_VALUE = TypeAdapter(JsonValue)


class RecordedModel(WrapperModel):
    def __init__(self, wrapped: Model, tools: MCPTools, output_schema: dict[str, JsonValue] | None = None) -> None:
        super().__init__(wrapped)
        self.tools = tools
        self.output_schema = output_schema or PlanDecision.model_json_schema()

    async def request(self, messages: list[ModelMessage], model_settings: ModelSettings | None,
                       model_request_parameters: ModelRequestParameters) -> ModelResponse:
        request: dict[str, JsonValue] = {
            "messages": JSON_VALUE.validate_python(ModelMessagesTypeAdapter.dump_python(messages, mode="json")),
            "model_settings": JSON_VALUE.validate_python(model_settings or {}),
            "output_schema": self.output_schema,
        }
        call = await self.tools.capture_start(self.wrapped.model_name, request)
        try:
            response = await self.wrapped.request(messages, model_settings, model_request_parameters)
        except asyncio.CancelledError:
            await self.tools.capture_finish(call.id, None, "Local model request was cancelled")
            raise
        except Exception as error:
            await self.tools.capture_finish(call.id, None, str(error))
            raise
        await self.tools.capture_finish(call.id, {
            "messages": JSON_VALUE.validate_python(ModelMessagesTypeAdapter.dump_python([response], mode="json")),
        })
        return response
