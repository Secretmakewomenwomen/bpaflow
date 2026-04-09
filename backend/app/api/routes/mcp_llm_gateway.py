from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.config import Settings, get_settings
from app.mcp.common import (
    build_initialize_result,
    build_tool_error_result,
    build_tool_success_result,
    build_tools_list_result,
    extract_rpc_method,
    extract_rpc_params,
    extract_tool_call,
    jsonrpc_error,
    jsonrpc_success,
)
from app.mcp.services.llm_gateway_service import LlmGatewayService

router = APIRouter(prefix="/mcp/llm-gateway", tags=["mcp-llm-gateway"])


def _format_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"event: {event}\ndata: {payload}\n\n"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "chat_completion",
        "description": "Run one chat completion and return the final assistant message.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "OpenAI style role/content messages.",
                },
                "model": {"type": "string", "description": "Optional model override."},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "stream_completion",
        "description": "Run a streaming completion and return collected delta chunks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "OpenAI style role/content messages.",
                },
                "model": {"type": "string", "description": "Optional model override."},
            },
            "required": ["messages"],
        },
    },
]


def get_mcp_llm_gateway_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LlmGatewayService:
    return LlmGatewayService(settings)


@router.post("", response_model=None)
def handle_mcp_llm_gateway(
    request: Request,
    payload: dict[str, Any],
    service: Annotated[LlmGatewayService, Depends(get_mcp_llm_gateway_service)],
) -> dict[str, Any] | StreamingResponse:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(request_id, code=-32600, message="Invalid Request")

    method = extract_rpc_method(payload)
    if method == "initialize":
        return jsonrpc_success(request_id, build_initialize_result(server_name="mcp-llm-gateway"))
    if method == "tools/list":
        return jsonrpc_success(request_id, build_tools_list_result(_TOOLS))
    if method != "tools/call":
        return jsonrpc_error(request_id, code=-32601, message="Method not found")

    params = extract_rpc_params(payload)
    tool_name, arguments = extract_tool_call(params)
    if tool_name is None:
        return jsonrpc_error(request_id, code=-32602, message="Invalid params")
    if tool_name not in {"chat_completion", "stream_completion"}:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="UNKNOWN_TOOL", message=f"Unsupported tool: {tool_name}"),
        )

    messages = arguments.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="messages must be a non-empty array"),
        )
    for item in messages:
        if not isinstance(item, dict):
            return jsonrpc_success(
                request_id,
                build_tool_error_result(code="INVALID_ARGUMENT", message="messages items must be objects"),
            )
    model = arguments.get("model")
    if model is not None and not isinstance(model, str):
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="model must be a string"),
        )
    temperature = arguments.get("temperature")
    if temperature is not None and not isinstance(temperature, (int, float)):
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="temperature must be a number"),
        )
    tools = arguments.get("tools")
    if tools is not None and not isinstance(tools, list):
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="tools must be an array"),
        )
    tool_choice = arguments.get("tool_choice")
    if tool_choice is not None and not isinstance(tool_choice, (str, dict)):
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="tool_choice must be string or object"),
        )

    try:
        if tool_name == "chat_completion":
            result = service.chat_completion(
                messages=messages,
                model=model,
                temperature=float(temperature) if temperature is not None else None,
                tools=tools,
                tool_choice=tool_choice,
            )
        else:
            if "text/event-stream" in request.headers.get("accept", "").lower():
                def generate() -> Iterator[str]:
                    try:
                        for chunk in service.iter_stream_completion(
                            messages=messages,
                            model=model,
                            temperature=float(temperature) if temperature is not None else None,
                            tools=tools,
                            tool_choice=tool_choice,
                        ):
                            yield _format_sse("delta", chunk)
                        yield _format_sse("done", {"ok": True, "model": model or service.settings.assistant_llm_model})
                    except Exception as exc:
                        yield _format_sse("error", {"message": str(exc)})

                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            result = service.stream_completion(
                messages=messages,
                model=model,
                temperature=float(temperature) if temperature is not None else None,
                tools=tools,
                tool_choice=tool_choice,
            )
    except Exception as exc:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="SERVICE_ERROR", message=str(exc)),
        )
    return jsonrpc_success(request_id, build_tool_success_result(result))
