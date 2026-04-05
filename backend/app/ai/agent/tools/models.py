from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple((_deep_freeze(item) for item in value))
    return value


@dataclass(frozen=True)
class ToolRetryPolicy:
    retryable: bool = False
    max_attempts: int | None = None
    backoff_seconds: float | None = None


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    category: str
    retryable: bool
    retry_policy: ToolRetryPolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "retryable": self.retryable,
        }
        if self.retry_policy is not None:
            result["retry_policy"] = {
                "retryable": self.retry_policy.retryable,
                "max_attempts": self.retry_policy.max_attempts,
                "backoff_seconds": self.retry_policy.backoff_seconds,
            }
        return result


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any | None = None
    error: ToolError | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            payload["data"] = self.data
        else:
            payload["error"] = self.error.to_dict() if self.error else {}
        return payload


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ToolBackendMetadata:
    service_attr: str | None = None
    method: str | None = None
    context_user_arg: str | None = None
    placeholder_response: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.placeholder_response is not None:
            object.__setattr__(self, "placeholder_response", _deep_freeze(self.placeholder_response))


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]
    backend_metadata: ToolBackendMetadata
    output_schema: Mapping[str, Any]
    idempotent: bool = True
    requires_confirmation: bool = False
    required_scopes: Sequence[str] = ()
    retry_policy: ToolRetryPolicy | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", _deep_freeze(self.parameters))
        object.__setattr__(self, "output_schema", _deep_freeze(self.output_schema))
        object.__setattr__(self, "required_scopes", tuple(self.required_scopes))
