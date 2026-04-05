from __future__ import annotations

from types import MappingProxyType
from typing import Any, Sequence

from .models import (
    ToolBackendMetadata,
    ToolDefinition,
    ToolRetryPolicy,
    _deep_freeze,
)

_FILE_TYPE_FILTERS = ["pdf", "image", "document"]


def _build_object_schema(
    *,
    properties: dict[str, Any],
    required: Sequence[str] | None = None,
    description: str | None = None,
) -> MappingProxyType:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(required) if required else [],
    }
    if description:
        schema["description"] = description
    return _deep_freeze(schema)


def _build_output_schema(
    *,
    properties: dict[str, Any] | None = None,
    description: str | None = None,
) -> MappingProxyType:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if description:
        schema["description"] = description
    return _deep_freeze(schema)


_TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name="query_users",
        description="查询用户信息时调用此工具",
        parameters=_build_object_schema(properties={}, description="No arguments are required."),
        output_schema=_build_output_schema(
            properties={
                "users": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "user_id": {"type": "string"},
                            "username": {"type": "string"},
                        },
                    },
                },
            },
            description="A list of workspace users.",
        ),
        idempotent=True,
        requires_confirmation=False,
        required_scopes=("workspace:read_users",),
        retry_policy=ToolRetryPolicy(retryable=True, max_attempts=2),
        backend_metadata=ToolBackendMetadata(service_attr="work_service", method="queryUsers"),
    ),
    ToolDefinition(
        name="list_recent_files",
        description="通过可选过滤列出用户最近上传的内容。",
        parameters=_build_object_schema(
            properties={
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of files to return.",
                    "minimum": 1,
                },
                "file_type": {
                    "type": "string",
                    "description": "Optional file type filter.",
                    "enum": _FILE_TYPE_FILTERS,
                },
            },
            description="Optional paging/filter arguments. User identity supplied by backend.",
        ),
        output_schema=_build_output_schema(
            properties={
                "uploads": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
            description="Recent uploads for the active user.",
        ),
        idempotent=True,
        requires_confirmation=False,
        required_scopes=("uploads:list",),
        retry_policy=ToolRetryPolicy(retryable=True, max_attempts=2),
        backend_metadata=ToolBackendMetadata(
            service_attr="upload_service",
            method="list_uploads",
            context_user_arg="user_id",
        ),
    ),
    ToolDefinition(
        name="get_file_detail",
        description="查询指定文件详情信息时侯调用此工具",
        parameters=_build_object_schema(
            properties={
                "upload_id": {"type": "integer", "description": "Upload record identifier."},
            },
            required=["upload_id"],
            description="upload_id is required. User identity supplied by backend.",
        ),
        output_schema=_build_output_schema(
            properties={
                "uploadId": {"type": "integer"},
                "userId": {"type": "string"},
            },
            description="Metadata for a single upload.",
        ),
        idempotent=True,
        requires_confirmation=False,
        required_scopes=("uploads:read",),
        retry_policy=ToolRetryPolicy(retryable=True, max_attempts=1),
        backend_metadata=ToolBackendMetadata(
            service_attr="upload_service",
            method="get_file_detail",
            context_user_arg="user_id",
        ),
    ),
    ToolDefinition(
        name="search_knowledge_base",
        description="检索与查询相关的知识库片段时调用此工具",
        parameters=_build_object_schema(
            properties={
                "query": {"type": "string", "description": "Natural-language query text."},
                "top_k": {
                    "type": "integer",
                    "description": "Limit on the number of retrieved snippets.",
                    "minimum": 1,
                },
            },
            required=["query"],
            description="Query text is required. User identity supplied by backend.",
        ),
        output_schema=_build_output_schema(
            properties={
                "query": {"type": "string"},
                "snippets": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            description="Retrieval result from the knowledge base.",
        ),
        idempotent=True,
        requires_confirmation=False,
        required_scopes=("rag:search",),
        retry_policy=ToolRetryPolicy(retryable=True, max_attempts=2),
        backend_metadata=ToolBackendMetadata(
            service_attr="ai_rag_service",
            method="retrieve",
            context_user_arg="user_id",
        ),
    ),
]

_REGISTRY: dict[str, ToolDefinition] = {}
for tool in _TOOL_DEFINITIONS:
    if tool.name in _REGISTRY:
        raise ValueError(f"Duplicate tool definition: {tool.name}")
    _REGISTRY[tool.name] = tool


def list_tools() -> list[ToolDefinition]:
    return list(_REGISTRY.values())


def get_tool(tool_name: str) -> ToolDefinition:
    return _REGISTRY[tool_name]
