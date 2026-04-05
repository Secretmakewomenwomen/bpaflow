from __future__ import annotations

import logging

from collections.abc import Mapping
from typing import Any, Callable

from .models import (
    ToolBackendMetadata,
    ToolCall,
    ToolDefinition,
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


class ToolDispatcher:
    def __init__(
        self,
        *,
        work_service: Any | None = None,
        upload_service: Any | None = None,
        ai_rag_service: Any | None = None,
        current_user_id: str | None = None,
    ) -> None:
        self.work_service = work_service
        self.upload_service = upload_service
        self.ai_rag_service = ai_rag_service
        self.current_user_id = current_user_id

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
            result = self._dispatch(tool_def, args)
        except PermissionError as exc:
            return self._build_error(
                code="PERMISSION_DENIED",
                message=str(exc),
                category=_ERROR_CATEGORY_PERMISSION,
                retryable=False,
            )
        except ValueError as exc:
            return self._build_error(
                code="INVALID_ARGUMENT",
                message=str(exc),
                category=_ERROR_CATEGORY_VALIDATION,
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

        return ToolResult(ok=True, data=result)

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

    def _dispatch(self, tool_def: ToolDefinition, args: dict[str, Any]) -> Any:
        metadata: ToolBackendMetadata = tool_def.backend_metadata

        placeholder = metadata.placeholder_response
        if placeholder is not None:
            return self._thaw_placeholder(placeholder)

        service_attr = metadata.service_attr
        if not service_attr:
            raise RuntimeError("Tool backend is not configured.")

        service = getattr(self, service_attr)
        if service is None:
            raise RuntimeError(f"{service_attr} is not configured")

        method_name = metadata.method
        if method_name is None:
            raise RuntimeError(f"Method not configured for tool {tool_def.name}")

        method: Callable[..., Any] = getattr(service, method_name)

        call_args = dict(args)
        context_arg = metadata.context_user_arg
        if context_arg:
            user_id = self.current_user_id
            if user_id is None:
                raise PermissionError("User context is required")
            call_args[context_arg] = user_id

        return method(**call_args)

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
