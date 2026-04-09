from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Header
from fastapi.encoders import jsonable_encoder


@dataclass(slots=True)
class McpRequestContext:
    user_id: str | None
    tenant_id: str | None
    session_id: str | None
    trace_id: str | None


def get_mcp_request_context(
    x_user_id: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None),
) -> McpRequestContext:
    return McpRequestContext(
        user_id=x_user_id,
        tenant_id=x_tenant_id,
        session_id=x_session_id,
        trace_id=x_trace_id,
    )


def jsonrpc_success(request_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": jsonable_encoder(result),
    }


def jsonrpc_error(
    request_id: Any,
    *,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if data is not None:
        payload["error"]["data"] = jsonable_encoder(data)
    return payload


def build_initialize_result(*, server_name: str) -> dict[str, Any]:
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": server_name,
            "version": "0.1.0",
        },
        "capabilities": {
            "tools": {},
        },
    }


def build_tools_list_result(tools: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tools": tools}


def build_tool_success_result(data: Any) -> dict[str, Any]:
    payload = {
        "ok": True,
        "data": jsonable_encoder(data),
    }
    return {
        "isError": False,
        "structuredContent": payload,
        "content": [
            {
                "type": "text",
                "text": "ok",
                # Keep legacy compatibility for existing JSON payload parsers.
                "json": payload,
            }
        ]
    }


def build_tool_error_result(
    *,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
        },
    }
    return {
        "isError": True,
        "structuredContent": payload,
        "content": [
            {
                "type": "text",
                "text": message,
                # Keep legacy compatibility for existing JSON payload parsers.
                "json": payload,
            }
        ],
    }


def extract_rpc_method(payload: dict[str, Any]) -> str | None:
    method = payload.get("method")
    if isinstance(method, str):
        return method
    return None


def extract_rpc_params(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params")
    if isinstance(params, dict):
        return params
    return {}


def extract_tool_call(params: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    name = params.get("name")
    if not isinstance(name, str):
        return None, {}
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    return name, arguments
