from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionType(str, Enum):
    final_answer = "final_answer"
    tool_call = "tool_call"
    tool_arguments_error = "tool_arguments_error"
    decision_error = "decision_error"


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    tool_args: dict[str, Any]
    call_id: str | None = None


@dataclass
class AgentDecision:
    decision_type: DecisionType
    thought: str | None = None
    final_answer: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    error_message: str | None = None
