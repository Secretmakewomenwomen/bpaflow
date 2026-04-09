from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.ai.services.ai_rag_service import AIRagService
from app.core.config import Settings, get_settings
from app.core.database import get_tenant_engine, get_tenant_id
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
from app.services.pgvector_service import PgVectorService

router = APIRouter(prefix="/mcp/rag", tags=["mcp-rag"])

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge_base",
        "description": "Search snippets from the knowledge base for the current user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query."},
                "top_k": {"type": "integer", "description": "Optional max snippets.", "minimum": 1},
            },
            "required": ["query"],
        },
    }
]


def get_mcp_rag_service(
    settings: Annotated[Settings, Depends(get_settings)],
    tenant_id: Annotated[str, Depends(get_tenant_id)],
) -> AIRagService:
    tenant_engine = get_tenant_engine(tenant_id)
    return AIRagService(
        settings=settings,
        pgvector_service=PgVectorService(settings=settings, engine=tenant_engine),
    )


@router.post("")
def handle_mcp_rag(
    payload: dict[str, Any],
    service: Annotated[AIRagService, Depends(get_mcp_rag_service)],
    context: Annotated[McpRequestContext, Depends(get_mcp_request_context)],
) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(request_id, code=-32600, message="Invalid Request")

    method = extract_rpc_method(payload)
    if method == "initialize":
        return jsonrpc_success(request_id, build_initialize_result(server_name="mcp-rag"))
    if method == "tools/list":
        return jsonrpc_success(request_id, build_tools_list_result(_TOOLS))
    if method != "tools/call":
        return jsonrpc_error(request_id, code=-32601, message="Method not found")

    params = extract_rpc_params(payload)
    tool_name, arguments = extract_tool_call(params)
    if tool_name is None:
        return jsonrpc_error(request_id, code=-32602, message="Invalid params")
    if tool_name != "search_knowledge_base":
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="UNKNOWN_TOOL", message=f"Unsupported tool: {tool_name}"),
        )

    if not context.user_id:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="MISSING_USER_CONTEXT", message="x-user-id header is required"),
        )

    query = arguments.get("query")
    top_k = arguments.get("top_k")
    if not isinstance(query, str) or not query.strip():
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="query must be a non-empty string"),
        )
    if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="INVALID_ARGUMENT", message="top_k must be an integer > 0"),
        )

    try:
        result = service.retrieve(query=query, user_id=context.user_id, top_k=top_k)
    except Exception as exc:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="SERVICE_ERROR", message=str(exc)),
        )
    return jsonrpc_success(request_id, build_tool_success_result(result))

