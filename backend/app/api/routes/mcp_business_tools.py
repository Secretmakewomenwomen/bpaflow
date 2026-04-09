from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
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
from app.services.upload_service import UploadService
from app.services.work_service import WorkService

router = APIRouter(prefix="/mcp/business-tools", tags=["mcp-business-tools"])

_FILE_TYPE_FILTERS = ["pdf", "image", "document"]

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_users",
        "description": "Query all users from current tenant.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_recent_files",
        "description": "List user's recent uploaded files with optional filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1},
                "file_type": {"type": "string", "enum": _FILE_TYPE_FILTERS},
            },
            "required": [],
        },
    },
    {
        "name": "get_file_detail",
        "description": "Get one upload detail by upload_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "upload_id": {"type": "integer"},
            },
            "required": ["upload_id"],
        },
    },
]


def get_mcp_work_service(
    db: Annotated[Session, Depends(get_db)],
) -> WorkService:
    return WorkService(db=db)


def get_mcp_upload_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadService:
    return UploadService(db=db, settings=settings)


@router.post("")
def handle_mcp_business_tools(
    payload: dict[str, Any],
    work_service: Annotated[WorkService, Depends(get_mcp_work_service)],
    upload_service: Annotated[UploadService, Depends(get_mcp_upload_service)],
    context: Annotated[McpRequestContext, Depends(get_mcp_request_context)],
) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return jsonrpc_error(request_id, code=-32600, message="Invalid Request")

    method = extract_rpc_method(payload)
    if method == "initialize":
        return jsonrpc_success(request_id, build_initialize_result(server_name="mcp-business-tools"))
    if method == "tools/list":
        return jsonrpc_success(request_id, build_tools_list_result(_TOOLS))
    if method != "tools/call":
        return jsonrpc_error(request_id, code=-32601, message="Method not found")

    params = extract_rpc_params(payload)
    tool_name, arguments = extract_tool_call(params)
    if tool_name is None:
        return jsonrpc_error(request_id, code=-32602, message="Invalid params")
    if tool_name not in {"query_users", "list_recent_files", "get_file_detail"}:
        return jsonrpc_success(
            request_id,
            build_tool_error_result(code="UNKNOWN_TOOL", message=f"Unsupported tool: {tool_name}"),
        )

    try:
        if tool_name == "query_users":
            users = work_service.queryUsers()
            result = {"users": users}
        elif tool_name == "list_recent_files":
            if not context.user_id:
                raise ValueError("x-user-id header is required")
            limit = arguments.get("limit")
            file_type = arguments.get("file_type")
            if limit is not None and (not isinstance(limit, int) or limit <= 0):
                raise ValueError("limit must be an integer > 0")
            if file_type is not None and file_type not in _FILE_TYPE_FILTERS:
                raise ValueError(f"file_type must be one of {_FILE_TYPE_FILTERS}")
            uploads = upload_service.list_uploads(
                context.user_id,
                limit=limit,
                file_type=file_type,
            )
            result = {"uploads": uploads}
        else:
            if not context.user_id:
                raise ValueError("x-user-id header is required")
            upload_id = arguments.get("upload_id")
            if not isinstance(upload_id, int):
                raise ValueError("upload_id must be an integer")
            detail = upload_service.get_file_detail(upload_id, user_id=context.user_id)
            result = detail
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

