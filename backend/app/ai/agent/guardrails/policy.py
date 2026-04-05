from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.ai.agent.reasoning.models import ToolCall
from app.ai.agent.state.models import AgentSessionState
from app.ai.agent.tools.models import ToolDefinition


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    error_code: str | None = None
    detail: str | None = None


class GuardrailsPolicy:
    def validate_tool_call(
        self,
        state: AgentSessionState,
        tool_definition: ToolDefinition,
        tool_call: ToolCall,
        *,
        confirmation: bool = False,
    ) -> GuardrailResult:
        if not state.user_id:
            return GuardrailResult(
                allowed=False,
                error_code="UNAUTHENTICATED",
                detail="User context is required before invoking tools.",
            )

        if tool_call.tool_name != tool_definition.name:
            return GuardrailResult(
                allowed=False,
                error_code="TOOL_MISMATCH",
                detail=f"Tool call refers to '{tool_call.tool_name}' but guardrails expect '{tool_definition.name}'.",
            )

        missing = self._missing_required_arguments(tool_definition.parameters, tool_call.tool_args)
        if missing:
            return GuardrailResult(
                allowed=False,
                error_code="MISSING_ARGUMENTS",
                detail=f"Missing required arguments: {', '.join(missing)}",
            )

        if tool_definition.requires_confirmation and not confirmation:
            return GuardrailResult(
                allowed=False,
                error_code="CONFIRMATION_REQUIRED",
                detail="This tool requires explicit confirmation before execution.",
            )

        return GuardrailResult(allowed=True)

    @staticmethod
    def _missing_required_arguments(
        schema: Mapping[str, Any],
        arguments: dict[str, Any] | None,
    ) -> list[str]:
        required = schema.get("required") or []
        args = arguments or {}
        missing = [name for name in required if name not in args]
        return missing
