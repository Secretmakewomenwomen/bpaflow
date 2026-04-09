from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.mcp.common import (
    McpRequestContext,
    build_initialize_result,
    build_tool_error_result,
    build_tool_success_result,
    build_tools_list_result,
    extract_rpc_method,
    extract_rpc_params,
    extract_tool_call,
    get_mcp_request_context,
    jsonrpc_error,
    jsonrpc_success,
)
from app.mcp.services.memory_service import MemoryToolService

router = APIRouter(prefix="/mcp/memory", tags=["mcp-memory"])

_MEMORY_SERVICE = MemoryToolService()

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "memory_read",
        "description": "Read memory items for the current session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional session override."},
                "limit": {"type": "integer", "description": "Optional max item count.", "minimum": 1},
            },
            "required": [],
        },
    },
    {
        "name": "memory_append",
        "description": "Append one memory item into the current session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional session override."},
                "content": {"type": "string", "description": "Memory content text."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "memory_summarize",
        "description": "Build a compact summary from recent session memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Optional session override."},
                "max_items": {"type": "integer", "description": "Max items included.", "minimum": 1},
            },
            "required": [],
        },
    },
]


def get_mcp_memory_service() -> MemoryToolService:
    return _MEMORY_SERVICE


def _resolve_session_id(arguments: dict[str, Any], context: McpRequestContext) -> str | None:
    session_id = arguments.get("session_id")
    if isinstance(session_id, str) and session_id.strip():
        return session_id.strip()
    return context.session_id


@router.post("")
def handle_mcp_memory(
    payload: dict[str, Any],
    service: Annotated[MemoryToolService, Depends(get_mcp_memory_service)],
    context: Annotated[McpRequestContext, Depends(get_mcp_request_context)],
) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(request_id, code=-32600, message="Invalid Request")

    method = extract_rpc_method(payload)
    if method == "initialize":
        return jsonrpc_success(request_id, build_initialize_result(server_name="mcp-memory"))
    if method == "tools/list":
        return jsonrpc_success(request_id, build_tools_list_result(_TOOLS))
    if method != "tools/call":
        return jsonrpc_error(request_id, code=-32601, message="Method not found")

    params = extract_rpc_params(payload)
    tool_name, arguments = extract_tool_call(params)
    if tool_name is None:
        return jsonrpc_error(request_id, code=-32602, message="Invalid params")
    if tool_name not in {"memory_read", "memory_append", "memory_summarize"}:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="UNKNOWN_TOOL", message=f"Unsupported tool: {tool_name}"),
        )

    session_id = _resolve_session_id(arguments, context)
    if not session_id:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="MISSING_SESSION_CONTEXT", message="x-session-id header is required"),
        )

    try:
        if tool_name == "memory_read":
            limit = arguments.get("limit", 20)
            result = service.memory_read(session_id=session_id, limit=int(limit))
        elif tool_name == "memory_append":
            content = arguments.get("content")
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            result = service.memory_append(session_id=session_id, content=content)
        else:
            max_items = arguments.get("max_items", 20)
            result = service.memory_summarize(session_id=session_id, max_items=int(max_items))
    except ValueError as exc:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message=str(exc)),
        )
    except Exception as exc:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="SERVICE_ERROR", message=str(exc)),
        )

    return jsonrpc_success(request_id, build_tool_success_result(result))

