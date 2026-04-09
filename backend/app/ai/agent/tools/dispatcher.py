from __future__ import annotations

import logging
import uuid

from collections.abc import Mapping
from typing import Any

from app.mcp.client import McpSessionClient

from .models import (
    ToolCall,
    ToolError,
    ToolResult,
    ToolRetryPolicy,
)
from .registry import get_tool

logger = logging.getLogger(__name__)

_ERROR_CATEGORY_UNKNOWN = "unknown"
_ERROR_CATEGORY_VALIDATION = "validation"
_ERROR_CATEGORY_PERMISSION = "permission"
_ERROR_CATEGORY_SERVICE = "service"

_TOOL_TO_SERVER: dict[str, str] = {
    "query_users": "business_tools",
    "list_recent_files": "business_tools",
    "get_file_detail": "business_tools",
    "search_knowledge_base": "rag",
    "memory_read": "memory",
    "memory_append": "memory",
    "memory_summarize": "memory",
    "chat_completion": "llm_gateway",
    "stream_completion": "llm_gateway",
}


def _category_from_error_code(code: str) -> str:
    if code == "INVALID_ARGUMENT":
        return _ERROR_CATEGORY_VALIDATION
    if code in {"PERMISSION_DENIED", "MISSING_USER_CONTEXT", "MISSING_SESSION_CONTEXT"}:
        return _ERROR_CATEGORY_PERMISSION
    if code == "UNKNOWN_TOOL":
        return _ERROR_CATEGORY_UNKNOWN
    return _ERROR_CATEGORY_SERVICE


def _default_mcp_endpoints(settings: Any | None) -> dict[str, str]:
    if settings is None:
        return {
            "rag": "http://127.0.0.1:8000/api/mcp/rag",
            "memory": "http://127.0.0.1:8000/api/mcp/memory",
            "llm_gateway": "http://127.0.0.1:8000/api/mcp/llm-gateway",
            "business_tools": "http://127.0.0.1:8000/api/mcp/business-tools",
        }
    return {
        "rag": getattr(settings, "assistant_mcp_rag_url"),
        "memory": getattr(settings, "assistant_mcp_memory_url"),
        "llm_gateway": getattr(
            settings,
            "assistant_mcp_llm_gateway_url",
        ),
        "business_tools": getattr(
            settings,
            "assistant_mcp_business_tools_url",
        ),
    }


class ToolDispatcher:
    def __init__(
        self,
        *,
        settings: Any | None = None,
        work_service: Any | None = None,
        upload_service: Any | None = None,
        ai_rag_service: Any | None = None,
        current_user_id: str | None = None,
        current_tenant_id: str | None = None,
        current_session_id: str | None = None,
        current_trace_id: str | None = None,
        mcp_client: Any | None = None,
        mcp_session_client: McpSessionClient | None = None,
        mcp_endpoints: Mapping[str, str] | None = None,
        request_timeout_seconds: float | None = None,
    ) -> None:
        # Local service fields are kept only for backward-compatible constructor signatures.
        self.settings = settings
        self.work_service = work_service
        self.upload_service = upload_service
        self.ai_rag_service = ai_rag_service
        self.current_user_id = current_user_id
        self.current_tenant_id = current_tenant_id
        self.current_session_id = current_session_id
        self.current_trace_id = current_trace_id
        default_timeout = float(getattr(settings, "assistant_mcp_request_timeout_seconds", 20.0))
        self.request_timeout_seconds = float(request_timeout_seconds or default_timeout)
        self.mcp_endpoints = dict(mcp_endpoints or _default_mcp_endpoints(settings))
        # Legacy injected client (typically tests) still supports .post-based JSON-RPC calls.
        self._mcp_client = mcp_client
        self._mcp_session_client = mcp_session_client or McpSessionClient()

    def execute(self, call: ToolCall) -> ToolResult:
        tool_name = call.tool_name
        try:
            tool_def = get_tool(tool_name)
        except KeyError:
            return self._build_error(
                code="UNKNOWN_TOOL",
                message=f"Tool '{tool_name}' is not registered.",
                category=_ERROR_CATEGORY_UNKNOWN,
                retryable=False,
            )

        args = dict(call.arguments or {})
        validation_error = self._validate_arguments(tool_def.parameters, args)
        if validation_error is not None:
            return self._build_error(
                code="INVALID_ARGUMENT",
                message=validation_error,
                category=_ERROR_CATEGORY_VALIDATION,
                retryable=False,
            )

        try:
            return self._dispatch_via_mcp(tool_name=tool_name, args=args, retry_policy=tool_def.retry_policy)
        except ValueError as exc:
            return self._build_error(
                code="INVALID_ARGUMENT",
                message=str(exc),
                category=_ERROR_CATEGORY_VALIDATION,
                retryable=False,
            )
        except PermissionError as exc:
            return self._build_error(
                code="PERMISSION_DENIED",
                message=str(exc),
                category=_ERROR_CATEGORY_PERMISSION,
                retryable=False,
            )
        except Exception as exc:
            logger.exception("Tool %s execution failed unexpectedly", tool_name, exc_info=exc)
            return self._build_error(
                code="SERVICE_ERROR",
                message=f"Tool '{tool_name}' failed to execute.",
                category=_ERROR_CATEGORY_SERVICE,
                retryable=False,
                retry_policy=tool_def.retry_policy,
            )

    def _dispatch_via_mcp(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        retry_policy: ToolRetryPolicy | None = None,
    ) -> ToolResult:
        server_key = _TOOL_TO_SERVER.get(tool_name)
        if server_key is None:
            return self._build_error(
                code="UNKNOWN_TOOL",
                message=f"Tool '{tool_name}' is not mapped to an MCP server.",
                category=_ERROR_CATEGORY_UNKNOWN,
                retryable=False,
            )

        endpoint = self.mcp_endpoints.get(server_key)
        if not endpoint:
            raise RuntimeError(f"MCP endpoint is not configured for server '{server_key}'.")

        headers: dict[str, str] = {}
        if self.current_user_id:
            headers["x-user-id"] = self.current_user_id
        if self.current_tenant_id:
            headers["x-tenant-id"] = self.current_tenant_id
        if self.current_session_id:
            headers["x-session-id"] = self.current_session_id
        if self.current_trace_id:
            headers["x-trace-id"] = self.current_trace_id

        request_payload = {
            "jsonrpc": "2.0",
            "id": f"tool-{uuid.uuid4().hex}",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": args,
            },
        }

        if self._mcp_client is not None and hasattr(self._mcp_client, "post"):
            try:
                response = self._mcp_client.post(
                    endpoint,
                    json=request_payload,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
            except Exception as exc:
                raise RuntimeError(f"Failed to call MCP server '{server_key}': {exc}") from exc

            status_code = getattr(response, "status_code", 200)
            if status_code >= 400:
                raise RuntimeError(f"MCP server '{server_key}' returned HTTP {status_code}.")

            try:
                body = response.json()
            except Exception as exc:
                raise RuntimeError(f"MCP server '{server_key}' returned non-JSON response.") from exc
        else:
            try:
                body = self._mcp_session_client.call_tool(
                    endpoint=endpoint,
                    tool_name=tool_name,
                    arguments=args,
                    headers=headers,
                    timeout_seconds=self.request_timeout_seconds,
                )
            except Exception as exc:
                raise RuntimeError(f"Failed to call MCP server '{server_key}': {exc}") from exc

        if not isinstance(body, Mapping):
            raise RuntimeError(f"MCP server '{server_key}' returned an invalid payload.")

        rpc_error = body.get("error")
        if isinstance(rpc_error, Mapping):
            rpc_code = str(rpc_error.get("code") or "JSONRPC_ERROR")
            rpc_message = str(rpc_error.get("message") or "MCP JSON-RPC error")
            return self._build_error(
                code=rpc_code,
                message=rpc_message,
                category=_ERROR_CATEGORY_SERVICE,
                retryable=retry_policy.retryable if retry_policy is not None else False,
                retry_policy=retry_policy,
            )

        payload = self._extract_tool_payload(body)

        ok = bool(payload.get("ok"))
        if ok:
            return ToolResult(ok=True, data=payload.get("data"))

        error_obj = payload.get("error")
        if not isinstance(error_obj, Mapping):
            return self._build_error(
                code="SERVICE_ERROR",
                message=f"Tool '{tool_name}' failed with malformed MCP error payload.",
                category=_ERROR_CATEGORY_SERVICE,
                retryable=retry_policy.retryable if retry_policy is not None else False,
                retry_policy=retry_policy,
            )

        error_code = str(error_obj.get("code") or "SERVICE_ERROR")
        error_message = str(error_obj.get("message") or f"Tool '{tool_name}' failed.")
        retryable = bool(error_obj.get("retryable"))
        return self._build_error(
            code=error_code,
            message=error_message,
            category=_category_from_error_code(error_code),
            retryable=retryable,
            retry_policy=retry_policy,
        )

    @staticmethod
    def _extract_tool_payload(body: Mapping[str, Any]) -> Mapping[str, Any]:
        # Legacy direct HTTP JSON-RPC shape: {"result": { ...CallToolResult }}
        result_obj = body.get("result")
        if isinstance(result_obj, Mapping):
            source = result_obj
        else:
            # ClientSession shape: directly returns CallToolResult.
            source = body

        structured = source.get("structuredContent")
        if isinstance(structured, Mapping):
            if "ok" in structured:
                return structured

        content = source.get("content")
        if isinstance(content, list) and content:
            first_item = content[0]
            if isinstance(first_item, Mapping):
                payload = first_item.get("json")
                if isinstance(payload, Mapping):
                    return payload
                text = first_item.get("text")
                if isinstance(text, str) and bool(source.get("isError")):
                    return {
                        "ok": False,
                        "error": {
                            "code": "SERVICE_ERROR",
                            "message": text,
                            "retryable": False,
                        },
                    }

        if bool(source.get("isError")):
            return {
                "ok": False,
                "error": {
                    "code": "SERVICE_ERROR",
                    "message": "mcp tool failed",
                    "retryable": False,
                },
            }
        return {"ok": True, "data": structured}

    def _validate_arguments(self, schema: Mapping[str, Any], provided: dict[str, Any]) -> str | None:
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for name in required:
            if name not in provided:
                return f"Missing required argument: {name}"

        for arg_name, value in provided.items():
            if arg_name not in properties:
                return f"Unexpected argument: {arg_name}"

            if value is None:
                if arg_name in required:
                    return f"Argument {arg_name} must not be null"
                continue

            prop_schema = properties[arg_name]
            expected_type = prop_schema.get("type")
            if expected_type and not self._matches_type(value, expected_type):
                return f"Argument {arg_name} must be {expected_type}"

            if "minimum" in prop_schema and isinstance(value, int):
                if value < prop_schema["minimum"]:
                    return f"Argument {arg_name} must be >= {prop_schema['minimum']}"

            if "enum" in prop_schema and value not in prop_schema["enum"]:
                return f"Argument {arg_name} must be one of {prop_schema['enum']}"

        return None

    @staticmethod
    def _matches_type(value: Any, expected_type: str) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        return True

    @staticmethod
    def _thaw_placeholder(value: Mapping[str, Any]) -> dict[str, Any]:
        return {key: ToolDispatcher._thaw(item) for key, item in value.items()}

    @staticmethod
    def _thaw(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: ToolDispatcher._thaw(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [ToolDispatcher._thaw(item) for item in value]
        return value

    @staticmethod
    def _build_error(
        *,
        code: str,
        message: str,
        category: str,
        retryable: bool,
        retry_policy: ToolRetryPolicy | None = None,
    ) -> ToolResult:
        error = ToolError(
            code=code,
            message=message,
            category=category,
            retryable=retry_policy.retryable if retry_policy is not None else retryable,
            retry_policy=retry_policy,
        )
        return ToolResult(ok=False, error=error)
